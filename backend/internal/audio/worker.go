package audio

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// TranscriptSink receives every transcript envelope this worker produces. The
// SessionManager binds it to one owner, so a worker can only ever deliver to
// the owner whose audio it is transcribing.
type TranscriptSink func(data []byte)

// transcriptEnvelope wraps an audio transcript line for WebSocket delivery.
type transcriptEnvelope struct {
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload"`
}

// cancelWaitDelay bounds how long a cancelled subprocess may outlive SIGTERM
// before it is SIGKILLed (exec.Cmd.WaitDelay).
const cancelWaitDelay = 2 * time.Second

// Worker manages one Python audio subprocess: one owner's private STT stream.
type Worker struct {
	pythonBin    string
	scriptPath   string
	workDir      string
	whisperModel string
	sink         TranscriptSink
	cmd          *exec.Cmd
	procMu       sync.Mutex
	stdinPipe    io.WriteCloser
	stdinMu      sync.Mutex
	restartDelay time.Duration
	running      atomic.Bool
	muted        atomic.Bool
	log          zerolog.Logger
}

// Running reports whether the audio subprocess is currently alive.
func (w *Worker) Running() bool {
	return w.running.Load()
}

// setStdinPipe stores the current stdin pipe under stdinMu.
func (w *Worker) setStdinPipe(p io.WriteCloser) {
	w.stdinMu.Lock()
	w.stdinPipe = p
	w.stdinMu.Unlock()
}

// closeStdin closes the subprocess stdin so the Python read loop sees EOF and
// exits on its own. Safe to call when no subprocess is running.
func (w *Worker) closeStdin() {
	w.stdinMu.Lock()
	pipe := w.stdinPipe
	w.stdinPipe = nil
	w.stdinMu.Unlock()
	if pipe != nil {
		_ = pipe.Close()
	}
}

// New creates a new Worker whose transcripts are delivered to sink.
func New(pythonBin, scriptPath, workDir, whisperModel string, sink TranscriptSink) *Worker {
	return &Worker{
		pythonBin:    pythonBin,
		scriptPath:   scriptPath,
		workDir:      workDir,
		whisperModel: whisperModel,
		sink:         sink,
		restartDelay: 2 * time.Second,
		log:          log.With().Str("component", "audio-worker").Logger(),
	}
}

// Start launches the Python audio subprocess and restarts it after a bounded
// backoff whenever it exits for any reason other than context cancellation.
func (w *Worker) Start(ctx context.Context) error {
	for {
		err := w.run(ctx)
		if ctx.Err() != nil {
			return nil
		}
		w.log.Error().Err(err).Msg("audio process exited unexpectedly, restarting")
		select {
		case <-time.After(w.restartDelay):
		case <-ctx.Done():
			return nil
		}
	}
}

func (w *Worker) run(ctx context.Context) error {
	w.setStdinPipe(nil)

	cmd := exec.CommandContext(ctx, w.pythonBin, "-u", w.scriptPath, "--model", w.whisperModel)
	cmd.Dir = w.workDir
	cmd.Env = append(os.Environ(), "PYTHONPATH="+w.workDir)
	// On context cancel ask the process to stop (SIGTERM) and only SIGKILL it
	// after cancelWaitDelay, so a per-session teardown is graceful and bounded.
	cmd.Cancel = func() error { return cmd.Process.Signal(syscall.SIGTERM) }
	cmd.WaitDelay = cancelWaitDelay

	stdin, err := cmd.StdinPipe()
	if err != nil {
		return err
	}

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		w.log.Error().Err(err).Str("bin", w.pythonBin).Str("script", w.scriptPath).Msg("failed to start audio process")
		return err
	}

	// Publish the process handle only after Start() has fully populated it, so a
	// concurrent Stop() (guarded by procMu) observes a stable, started process.
	w.procMu.Lock()
	w.cmd = cmd
	w.procMu.Unlock()

	w.setStdinPipe(stdin)
	w.running.Store(true)
	defer w.running.Store(false)
	w.log.Info().Int("pid", cmd.Process.Pid).Msg("audio process started")

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			if !strings.HasPrefix(line, "{") {
				w.log.Debug().Str("line", line).Msg("skipping non-json line from audio process")
				continue
			}
			env := transcriptEnvelope{
				Type:    "transcript",
				Payload: json.RawMessage(line),
			}
			data, err := json.Marshal(env)
			if err != nil {
				w.log.Error().Err(err).Msg("failed to marshal transcript envelope")
				continue
			}
			w.sink(data)
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			// The worker's own structured records arrive here (its stdout is the
			// transcript transport), so relay at Info rather than inflating to Warn.
			w.log.Info().Str("source", "python-audio").Msg(scanner.Text())
		}
	}()

	// Drain the scanner goroutines to EOF before reaping. cmd.Wait closes the
	// stdout/stderr pipes on process exit, so reaping first can truncate an
	// in-flight read and drop the run's output.
	wg.Wait()
	err = cmd.Wait()
	w.setStdinPipe(nil)
	if ctx.Err() != nil {
		return nil
	}
	return err
}

// Mute gates the browser audio stream at the Go edge. When muted, WriteAudio
// drops incoming PCM frames so the STT pipeline hears silence while ARIA speaks
// (TTS playback). Muting does not touch the subprocess stdin — that pipe
// carries raw PCM only.
func (w *Worker) Mute(muted bool) {
	w.muted.Store(muted)
}

// WriteAudio forwards one frame of raw Int16 PCM (16 kHz mono, little-endian)
// from the browser mic stream to the Python audio subprocess via stdin. Frames
// are dropped while muted, and silently ignored when no subprocess is running.
func (w *Worker) WriteAudio(pcm []byte) {
	if w.muted.Load() {
		return
	}
	w.stdinMu.Lock()
	pipe := w.stdinPipe
	w.stdinMu.Unlock()
	if pipe == nil {
		return
	}
	_, _ = pipe.Write(pcm)
}

// Stop sends SIGTERM to the process, then SIGKILL after 2 seconds.
// It does not call cmd.Wait() — run() owns the single Wait() call.
func (w *Worker) Stop() {
	w.procMu.Lock()
	cmd := w.cmd
	w.procMu.Unlock()
	if cmd == nil || cmd.Process == nil {
		return
	}
	cmd.Process.Signal(syscall.SIGTERM)
	time.Sleep(2 * time.Second)
	if cmd.Process != nil {
		cmd.Process.Kill()
	}
	w.log.Info().Msg("audio process stopped")
}

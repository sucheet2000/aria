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

// Broadcaster is satisfied by any type that can broadcast raw bytes to clients.
// BroadcastScoped delivers a frame only to the owner that claims the local
// perception stream, so transcripts do not leak across users.
type Broadcaster interface {
	Broadcast([]byte)
	BroadcastScoped([]byte)
}

// transcriptEnvelope wraps an audio transcript line for WebSocket broadcast.
type transcriptEnvelope struct {
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload"`
}

// Worker manages the Python audio subprocess.
type Worker struct {
	pythonBin    string
	scriptPath   string
	workDir      string
	whisperModel string
	hub          Broadcaster
	cmd          *exec.Cmd
	procMu       sync.Mutex
	stdinPipe    io.WriteCloser
	stdinMu      sync.Mutex
	restartDelay time.Duration
	running      atomic.Bool
	log          zerolog.Logger
}

// Running reports whether the audio subprocess is currently alive. It is used by
// the /ready probe to gate readiness on the always-on audio worker.
func (w *Worker) Running() bool {
	return w.running.Load()
}

// setStdinPipe stores the current stdin pipe under stdinMu.
func (w *Worker) setStdinPipe(p io.WriteCloser) {
	w.stdinMu.Lock()
	w.stdinPipe = p
	w.stdinMu.Unlock()
}

// New creates a new Worker.
func New(pythonBin, scriptPath, workDir, whisperModel string, hub Broadcaster) *Worker {
	return &Worker{
		pythonBin:    pythonBin,
		scriptPath:   scriptPath,
		workDir:      workDir,
		whisperModel: whisperModel,
		hub:          hub,
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
			w.hub.BroadcastScoped(data)
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			w.log.Warn().Str("source", "python-audio").Msg(scanner.Text())
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

// Mute sends a mute/unmute command to the Python audio process via stdin.
func (w *Worker) Mute(muted bool) {
	w.stdinMu.Lock()
	pipe := w.stdinPipe
	w.stdinMu.Unlock()
	if pipe == nil {
		return
	}
	payload := `{"mute":false}` + "\n"
	if muted {
		payload = `{"mute":true}` + "\n"
	}
	_, _ = pipe.Write([]byte(payload))
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

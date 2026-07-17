package vision

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Broadcaster is satisfied by any type that can broadcast raw bytes to clients.
// BroadcastScoped delivers a frame only to the owner that claims the local
// perception stream, so vision landmarks do not leak across users.
type Broadcaster interface {
	Broadcast([]byte)
	BroadcastScoped([]byte)
}

// Worker manages the Python vision subprocess.
type Worker struct {
	pythonBin     string
	scriptPath    string
	workDir       string
	hub           Broadcaster
	cmd           *exec.Cmd
	done          chan struct{}
	cancel        context.CancelFunc
	procMu        sync.Mutex
	stdin         io.WriteCloser
	stdinMu       sync.Mutex
	lastSessionID string
	restartDelay  time.Duration
	stopTimeout   time.Duration
	log           zerolog.Logger
}

// SetActiveSession writes the active frontend session ID to the vision worker's
// stdin so it can embed the concrete session ID in interrupt signals.
// The ID is also persisted so it can be replayed after a subprocess restart.
func (w *Worker) SetActiveSession(id string) {
	w.stdinMu.Lock()
	defer w.stdinMu.Unlock()
	w.lastSessionID = id
	if w.stdin == nil {
		return
	}
	w.writeSessionLocked(id)
}

// writeSessionLocked sends an active_session command to the subprocess stdin.
// Caller must hold stdinMu.
func (w *Worker) writeSessionLocked(id string) {
	msg, _ := json.Marshal(map[string]string{
		"type":       "active_session",
		"session_id": id,
	})
	_, _ = w.stdin.Write(append(msg, '\n'))
}

// New creates a new Worker.
func New(pythonBin, scriptPath, workDir string, hub Broadcaster) *Worker {
	return &Worker{
		pythonBin:    pythonBin,
		scriptPath:   scriptPath,
		workDir:      workDir,
		hub:          hub,
		restartDelay: 2 * time.Second,
		stopTimeout:  5 * time.Second,
		log:          log.With().Str("component", "vision-worker").Logger(),
	}
}

// Start launches the Python vision subprocess and restarts it after a bounded
// backoff whenever it exits for any reason other than context cancellation.
func (w *Worker) Start(ctx context.Context) error {
	w.procMu.Lock()
	if w.cancel != nil {
		w.procMu.Unlock()
		return nil
	}
	ctx, w.cancel = context.WithCancel(ctx)
	w.procMu.Unlock()
	defer func() {
		w.procMu.Lock()
		w.cancel = nil
		w.procMu.Unlock()
	}()

	for {
		err := w.run(ctx)
		if ctx.Err() != nil {
			return nil
		}
		w.log.Error().Err(err).Msg("vision process exited unexpectedly, restarting")
		select {
		case <-time.After(w.restartDelay):
		case <-ctx.Done():
			return nil
		}
	}
}

func (w *Worker) run(ctx context.Context) error {
	cmd := exec.CommandContext(ctx, w.pythonBin, w.scriptPath, "--grpc")
	cmd.Dir = w.workDir
	cmd.Env = append(os.Environ(), "PYTHONPATH="+cmd.Dir+":"+cmd.Dir+"/gen/python")

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}
	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		w.log.Error().Err(err).Str("bin", w.pythonBin).Str("script", w.scriptPath).Msg("failed to start vision process")
		return err
	}

	// Publish the process handle only after Start() has fully populated it, so a
	// concurrent Stop() (guarded by procMu) observes a stable, started process.
	// done is closed when this run returns (after its single cmd.Wait), letting
	// Stop() detect process exit without calling Wait() a second time.
	done := make(chan struct{})
	w.procMu.Lock()
	w.cmd = cmd
	w.done = done
	w.procMu.Unlock()
	defer close(done)

	w.stdinMu.Lock()
	w.stdin = stdinPipe
	lastSess := w.lastSessionID
	w.stdinMu.Unlock()

	// Replay the last known session ID after the subprocess has had time to
	// start reading stdin (covers worker restarts and first-connect races).
	if lastSess != "" {
		go func() {
			time.Sleep(500 * time.Millisecond)
			w.SetActiveSession(lastSess)
		}()
	}

	w.log.Info().Int("pid", cmd.Process.Pid).Msg("vision process started")

	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		var lastVisionBroadcast time.Time
		const visionFrameInterval = 200 * time.Millisecond

		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			if !strings.HasPrefix(line, "{") {
				w.log.Warn().Str("line", line).Msg("skipping non-json line from vision process")
				continue
			}
			now := time.Now()
			if now.Sub(lastVisionBroadcast) < visionFrameInterval {
				continue
			}
			lastVisionBroadcast = now
			wrapped := fmt.Sprintf(`{"type":"vision_state","payload":%s}`, line)
			w.hub.BroadcastScoped([]byte(wrapped))
		}
	}()

	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			w.log.Warn().Str("source", "python").Msg(scanner.Text())
		}
	}()

	// Drain the scanner goroutines to EOF before reaping. cmd.Wait closes the
	// stdout/stderr pipes on process exit, so reaping first can truncate an
	// in-flight read and drop the run's output.
	wg.Wait()
	err = cmd.Wait()
	w.stdinMu.Lock()
	w.stdin = nil
	w.stdinMu.Unlock()
	if ctx.Err() != nil {
		return nil
	}
	return err
}

// Stop cancels the run context, sends SIGTERM, waits up to stopTimeout for the
// process to exit, then sends SIGKILL. It does not call cmd.Wait() — run() owns
// the single Wait() call and closes done when it has reaped the process.
func (w *Worker) Stop() {
	w.procMu.Lock()
	cancel := w.cancel
	cmd := w.cmd
	done := w.done
	w.procMu.Unlock()

	if cancel != nil {
		cancel()
	}

	if cmd == nil || cmd.Process == nil {
		return
	}

	cmd.Process.Signal(syscall.SIGTERM)

	select {
	case <-done:
		w.log.Info().Msg("vision process stopped cleanly")
	case <-time.After(w.stopTimeout):
		w.log.Warn().Msg("vision process did not stop in time, sending sigkill")
		cmd.Process.Kill()
	}
}

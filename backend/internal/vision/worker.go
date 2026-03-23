package vision

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Broadcaster is satisfied by any type that can broadcast raw bytes to clients.
type Broadcaster interface {
	Broadcast([]byte)
}

// Worker manages the Python vision subprocess.
type Worker struct {
	pythonBin  string
	scriptPath string
	hub        Broadcaster
	cmd        *exec.Cmd
	log        zerolog.Logger
}

// New creates a new Worker.
func New(pythonBin, scriptPath string, hub Broadcaster) *Worker {
	return &Worker{
		pythonBin:  pythonBin,
		scriptPath: scriptPath,
		hub:        hub,
		log:        log.With().Str("component", "vision-worker").Logger(),
	}
}

// Start launches the Python vision subprocess and restarts it if it exits unexpectedly.
func (w *Worker) Start(ctx context.Context) error {
	for {
		if err := w.run(ctx); err != nil {
			return err
		}

		select {
		case <-ctx.Done():
			return nil
		default:
			w.log.Error().Msg("vision process exited unexpectedly, restarting in 2s")
			select {
			case <-time.After(2 * time.Second):
			case <-ctx.Done():
				return nil
			}
		}
	}
}

func (w *Worker) run(ctx context.Context) error {
	cmd := exec.CommandContext(ctx, w.pythonBin, w.scriptPath)
	cmd.Dir = "/Users/sucheetboppana/aria/backend"
	cmd.Env = append(os.Environ(), "PYTHONPATH="+cmd.Dir)
	w.cmd = cmd

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return err
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		return err
	}

	if err := cmd.Start(); err != nil {
		w.log.Error().Err(err).Str("bin", w.pythonBin).Str("script", w.scriptPath).Msg("failed to start vision process")
		return err
	}

	w.log.Info().Int("pid", cmd.Process.Pid).Msg("vision process started")

	go func() {
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
			w.hub.Broadcast([]byte(wrapped))
		}
	}()

	go func() {
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			w.log.Warn().Str("source", "python").Msg(scanner.Text())
		}
	}()

	err = cmd.Wait()
	if ctx.Err() != nil {
		return nil
	}
	return err
}

// Stop sends SIGTERM to the process, waits up to 5 seconds, then sends SIGKILL.
func (w *Worker) Stop() {
	if w.cmd == nil || w.cmd.Process == nil {
		return
	}

	w.cmd.Process.Signal(syscall.SIGTERM)

	done := make(chan error, 1)
	go func() {
		done <- w.cmd.Wait()
	}()

	select {
	case <-done:
		w.log.Info().Msg("vision process stopped cleanly")
	case <-time.After(5 * time.Second):
		w.log.Warn().Msg("vision process did not stop in time, sending sigkill")
		w.cmd.Process.Kill()
	}
}

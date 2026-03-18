package audio

import (
	"bufio"
	"context"
	"encoding/json"
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
	log          zerolog.Logger
}

// New creates a new Worker.
func New(pythonBin, scriptPath, workDir, whisperModel string, hub Broadcaster) *Worker {
	return &Worker{
		pythonBin:    pythonBin,
		scriptPath:   scriptPath,
		workDir:      workDir,
		whisperModel: whisperModel,
		hub:          hub,
		log:          log.With().Str("component", "audio-worker").Logger(),
	}
}

// Start launches the Python audio subprocess and restarts it if it exits unexpectedly.
func (w *Worker) Start(ctx context.Context) error {
	for {
		if err := w.run(ctx); err != nil {
			return err
		}

		select {
		case <-ctx.Done():
			return nil
		default:
			w.log.Error().Msg("audio process exited unexpectedly, restarting in 2s")
			select {
			case <-time.After(2 * time.Second):
			case <-ctx.Done():
				return nil
			}
		}
	}
}

func (w *Worker) run(ctx context.Context) error {
	cmd := exec.CommandContext(ctx, w.pythonBin, w.scriptPath, "--model", w.whisperModel)
	cmd.Dir = w.workDir
	cmd.Env = append(os.Environ(), "PYTHONPATH="+w.workDir)
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
		w.log.Error().Err(err).Str("bin", w.pythonBin).Str("script", w.scriptPath).Msg("failed to start audio process")
		return err
	}

	w.log.Info().Int("pid", cmd.Process.Pid).Msg("audio process started")

	go func() {
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
			w.hub.Broadcast(data)
		}
	}()

	go func() {
		scanner := bufio.NewScanner(stderr)
		for scanner.Scan() {
			w.log.Warn().Str("source", "python-audio").Msg(scanner.Text())
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
		w.log.Info().Msg("audio process stopped cleanly")
	case <-time.After(5 * time.Second):
		w.log.Warn().Msg("audio process did not stop in time, sending sigkill")
		w.cmd.Process.Kill()
	}
}

package main

import (
	"context"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/audio"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/server"
)

func main() {
	// Load .env file if present
	if data, err := os.ReadFile(".env"); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" || strings.HasPrefix(line, "#") {
				continue
			}
			parts := strings.SplitN(line, "=", 2)
			if len(parts) == 2 {
				key := strings.TrimSpace(parts[0])
				val := strings.TrimSpace(parts[1])
				if os.Getenv(key) == "" {
					os.Setenv(key, val)
				}
			}
		}
	}

	cfg := config.Load()

	// Structured JSON logs to stderr on the prod path (the zerolog default); the
	// human-readable ConsoleWriter is used only for local dev (DEBUG=true).
	if cfg.Debug {
		log.Logger = log.Output(zerolog.ConsoleWriter{
			Out:        os.Stdout,
			TimeFormat: time.RFC3339,
		})
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	} else {
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}

	wm := memory.New(10)

	execPath, err := os.Executable()
	if err != nil {
		log.Fatal().Err(err).Msg("cannot determine executable path")
	}
	workDir := filepath.Dir(execPath)
	if strings.Contains(workDir, "go-build") || strings.Contains(workDir, "temp") {
		workDir, _ = os.Getwd()
	}

	// The hub fans out broadcasts to connected WebSocket clients. Vision capture
	// now runs in the browser (A.2a), so the server no longer spawns a vision worker.
	// Interrupts are handled browser-side (the browser aborts its own in-flight
	// cognition request), so there is no server-side gRPC cognition path.
	hub := server.NewHub()

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// One Python STT worker per authenticated owner, started on that owner's
	// first /ws/audio connection and stopped on its last disconnect. Transcripts
	// are routed straight to the owning user's /ws clients (SEC-6).
	var audioSessions *audio.SessionManager
	if cfg.AudioEnabled {
		audioSessions = audio.NewSessionManager(
			ctx, cfg.PythonBin, cfg.AudioScript, workDir, cfg.WhisperModel,
			cfg.AudioMaxSessions, hub.BroadcastToOwner,
		)
		hub.SetAudio(audioSessions)
	}

	go hub.Run(ctx)

	// The server waits for FastAPI readiness (bounded, non-fatal) before it
	// begins serving so the first cognition request does not 500.
	srv := server.New(cfg, hub, wm)

	// Gate /ready on the audio session manager being able to spawn workers.
	if audioSessions != nil {
		srv.AddReadyCheck("audio", audioSessions.Ready)
	}

	go func() {
		if err := srv.Start(ctx); err != nil {
			log.Error().Err(err).Msg("server error")
			cancel()
		}
	}()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info().Msg("shutdown signal received")

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), server.ShutdownTimeout)
	defer shutdownCancel()

	if audioSessions != nil {
		server.GracefulShutdown(shutdownCtx, cancel, srv, audioSessions)
	} else {
		server.GracefulShutdown(shutdownCtx, cancel, srv)
	}

	log.Info().Msg("server stopped")
}

package main

import (
	"context"
	"net/http"
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
	"github.com/sucheet2000/aria/backend/internal/vision"
)

func main() {
	log.Logger = log.Output(zerolog.ConsoleWriter{
		Out:        os.Stdout,
		TimeFormat: time.RFC3339,
	})

	cfg := config.Load()

	if cfg.Debug {
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

	// Create hub first (nil vision) so the vision worker can reference it as a broadcaster.
	hub := server.NewHub(nil)

	// Create vision worker with hub as broadcaster, then wire it back into hub.
	worker := vision.New(cfg.PythonBin, cfg.VisionScript, hub)
	hub.SetVision(worker)

	audioWorker := audio.New(cfg.PythonBin, cfg.AudioScript, workDir, cfg.WhisperModel, hub)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go hub.Run(ctx)

	if cfg.AudioEnabled {
		go func() {
			if err := audioWorker.Start(ctx); err != nil {
				log.Error().Err(err).Msg("audio worker failed")
			}
		}()
	}

	// Wait for FastAPI to be ready before accepting cognition requests
	log.Info().Msg("waiting for FastAPI cognition service")
	for i := 0; i < 30; i++ {
		resp, err := http.Get("http://localhost:8000/health")
		if err == nil && resp.StatusCode == 200 {
			resp.Body.Close()
			log.Info().Msg("FastAPI cognition service ready")
			break
		}
		if i == 29 {
			log.Warn().Msg("FastAPI not ready after 30s, continuing anyway")
		}
		time.Sleep(time.Second)
	}

	srv := server.New(cfg, hub, wm)

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
	cancel()

	audioWorker.Stop()
	worker.Stop()

	time.Sleep(10 * time.Second)
	log.Info().Msg("server stopped")
}

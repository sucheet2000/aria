package main

import (
	"context"
	"os"
	"os/signal"
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

	hub := server.NewHub()
	go hub.Run()

	workDir := "/Users/sucheetboppana/aria/backend"

	worker := vision.New(cfg.PythonBin, cfg.VisionScript, hub)

	audioWorker := audio.New(cfg.PythonBin, cfg.AudioScript, workDir, cfg.WhisperModel, hub)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	go func() {
		if err := worker.Start(ctx); err != nil {
			log.Error().Err(err).Msg("vision worker exited with error")
		}
	}()

	if cfg.AudioEnabled {
		go func() {
			if err := audioWorker.Start(ctx); err != nil {
				log.Error().Err(err).Msg("audio worker failed")
			}
		}()
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

	time.Sleep(10 * time.Second)
	log.Info().Msg("server stopped")
}

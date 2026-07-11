package main

import (
	"context"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"github.com/sucheet2000/aria/backend/internal/audio"
	"github.com/sucheet2000/aria/backend/internal/cognition"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/server"
	"google.golang.org/grpc"
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
	hub := server.NewHub()

	// StreamRegistry bridges the CognitionService gRPC interrupt path and the HTTP handler.
	registry := cognition.NewStreamRegistry()

	// CognitionService gRPC server on :50052 — Python vision worker connects here.
	grpcSrv := grpc.NewServer()
	cognitionGRPC := cognition.NewCognitionGRPCServer(registry, hub, log.Logger)
	perceptionv1.RegisterCognitionServiceServer(grpcSrv, cognitionGRPC)
	lis, err := net.Listen("tcp", cfg.CognitionGRPCAddr)
	if err != nil {
		log.Fatal().Err(err).Str("addr", cfg.CognitionGRPCAddr).Msg("failed to bind CognitionService gRPC port")
	}
	go func() {
		log.Info().Str("addr", cfg.CognitionGRPCAddr).Msg("CognitionService gRPC server started")
		if err := grpcSrv.Serve(lis); err != nil {
			log.Error().Err(err).Msg("CognitionService gRPC server error")
		}
	}()

	audioWorker := audio.New(cfg.PythonBin, cfg.AudioScript, workDir, cfg.WhisperModel, hub)
	hub.SetAudio(audioWorker)

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

	// The server waits for FastAPI readiness (bounded, non-fatal) before it
	// begins serving so the first cognition request does not 500.
	srv := server.New(cfg, hub, wm, registry)

	// Gate /ready on the always-on audio worker.
	if cfg.AudioEnabled {
		srv.AddReadyCheck("audio", audioWorker.Running)
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

	server.GracefulShutdown(shutdownCtx, cancel, srv, grpcSrv, audioWorker)

	log.Info().Msg("server stopped")
}

package main

import (
	"context"
	"net"
	"net/http"
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
	arianats "github.com/sucheet2000/aria/backend/internal/nats"
	"github.com/sucheet2000/aria/backend/internal/server"
	"github.com/sucheet2000/aria/backend/internal/vision"
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

	// NATS subscriber: receives PerceptionFrames from Python vision worker (--nats mode).
	// Replaces GRPCClient for high-frequency landmark stream; gRPC retained for interrupts.
	natsSub := arianats.NewSubscriber(cfg.NatsURL, hub)
	if err := natsSub.Connect(); err != nil {
		log.Warn().Err(err).Str("url", cfg.NatsURL).Msg("NATS subscriber connect failed — vision frames will fall back to stdout")
	} else {
		defer natsSub.Close()
	}

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

	srv := server.New(cfg, hub, wm, registry)

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

	grpcSrv.GracefulStop()
	audioWorker.Stop()
	worker.Stop()

	time.Sleep(10 * time.Second)
	log.Info().Msg("server stopped")
}

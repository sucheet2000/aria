package server

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/cognition"
	"github.com/sucheet2000/aria/backend/internal/config"
)

// Server wraps the HTTP server and its dependencies.
type Server struct {
	router     *chi.Mux
	hub        *Hub
	cfg        *config.Config
	httpServer *http.Server
}

// New creates a new Server with the given configuration and hub.
func New(cfg *config.Config, hub *Hub) *Server {
	s := &Server{
		router: chi.NewRouter(),
		hub:    hub,
		cfg:    cfg,
	}
	return s
}

// Start registers routes, starts the HTTP server, and blocks until ctx is cancelled.
func (s *Server) Start(ctx context.Context) error {
	s.router.Use(middleware.RequestID)
	s.router.Use(middleware.Recoverer)

	s.router.Get("/health", s.handleHealth)
	s.router.Get("/ws", func(w http.ResponseWriter, r *http.Request) {
		ServeWs(s.hub, w, r)
	})

	cogClient := cognition.New(s.cfg.AnthropicKey, log.Logger)
	cogHandler := cognition.NewHandler(cogClient, log.Logger)

	s.router.Route("/api", func(r chi.Router) {
		r.Use(corsMiddleware)
		r.Post("/cognition", cogHandler.ServeHTTP)
	})

	s.httpServer = &http.Server{
		Addr:         s.cfg.Addr(),
		Handler:      s.router,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info().Str("addr", s.cfg.Addr()).Msg("http server listening")
		if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

	select {
	case <-ctx.Done():
	case err := <-errCh:
		return err
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	log.Info().Msg("shutting down http server")
	return s.httpServer.Shutdown(shutdownCtx)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"version": "0.1.0",
	})
}

// corsMiddleware adds permissive CORS headers for all /api/* routes so the
// frontend origin can reach the API during development.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

package server

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/cognition"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/tts"
)

// Server wraps the HTTP server and its dependencies.
type Server struct {
	router        *chi.Mux
	hub           *Hub
	cfg           *config.Config
	workingMemory *memory.WorkingMemory
	registry      *cognition.StreamRegistry
	httpServer    *http.Server
	httpClient    *http.Client
	pythonURL     string
}

// New creates a new Server with the given configuration, hub, working memory, and stream registry.
func New(cfg *config.Config, hub *Hub, wm *memory.WorkingMemory, registry *cognition.StreamRegistry) *Server {
	s := &Server{
		router:        chi.NewRouter(),
		hub:           hub,
		cfg:           cfg,
		workingMemory: wm,
		registry:      registry,
		httpClient:    &http.Client{Timeout: 10 * time.Second},
		pythonURL:     "http://localhost:8000",
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

	cogClient := cognition.NewWithLogger("http://localhost:8000/api/cognition", s.workingMemory, log.Logger)
	cogHandler := cognition.NewHandler(cogClient, s.registry, log.Logger)

	ttsClient := tts.New(s.cfg.ElevenLabsKey, s.cfg.ElevenLabsVoiceID)
	ttsHandler := tts.NewHandler(ttsClient)

	s.router.Route("/api", func(r chi.Router) {
		r.Use(corsMiddleware)
		r.Post("/cognition", cogHandler.ServeHTTP)
		r.Post("/tts", ttsHandler.ServeHTTP)
		r.Get("/memory/working", s.handleWorkingMemory)
		r.Get("/memory/profile", s.handleMemoryProfileProxy)
		r.Get("/anchors", s.handleAnchorsProxy)
		r.Delete("/anchors/{anchor_id}", s.handleAnchorDeleteProxy)
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

func (s *Server) handleWorkingMemory(w http.ResponseWriter, r *http.Request) {
	entries := s.workingMemory.All()
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(entries)
}

func (s *Server) handleMemoryProfileProxy(w http.ResponseWriter, r *http.Request) {
	resp, err := s.httpClient.Get(s.pythonURL + "/api/memory/profile")
	if err != nil {
		http.Error(w, `{"error":"python service unavailable"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body) //nolint:errcheck
}

func (s *Server) handleAnchorsProxy(w http.ResponseWriter, r *http.Request) {
	resp, err := s.httpClient.Get(s.pythonURL + "/api/anchors")
	if err != nil {
		http.Error(w, `{"error":"python service unavailable"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body) //nolint:errcheck
}

func (s *Server) handleAnchorDeleteProxy(w http.ResponseWriter, r *http.Request) {
	anchorID := chi.URLParam(r, "anchor_id")
	req, err := http.NewRequestWithContext(r.Context(), http.MethodDelete,
		s.pythonURL+"/api/anchors/"+anchorID, nil)
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	resp, err := s.httpClient.Do(req)
	if err != nil {
		http.Error(w, `{"error":"python service unavailable"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body) //nolint:errcheck
}

// corsMiddleware adds permissive CORS headers for all /api/* routes so the
// frontend origin can reach the API during development.
func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}

		next.ServeHTTP(w, r)
	})
}

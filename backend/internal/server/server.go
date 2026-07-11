package server

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/cognition"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/reqid"
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
	readyChecks   []readyCheck
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
		pythonURL:     cfg.PythonBaseURL,
	}
	s.httpServer = &http.Server{
		Addr:         cfg.Addr(),
		Handler:      s.router,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}
	return s
}

// Start registers routes, starts the HTTP server, and blocks until ctx is cancelled.
func (s *Server) Start(ctx context.Context) error {
	s.router.Use(requestIDMiddleware(log.Logger))
	s.router.Use(middleware.Recoverer)

	authEnabled := s.cfg.ClerkSecretKey != ""
	var verifier auth.Verifier
	if authEnabled {
		verifier = auth.NewClerkVerifier(s.cfg.ClerkSecretKey, s.cfg.ClerkJWTIssuer)
		log.Info().Msg("clerk auth enabled on /api and /ws")
	} else {
		if !isLoopback(s.cfg.Host) && os.Getenv("ALLOW_INSECURE_NO_AUTH") != "1" {
			log.Fatal().Msgf(
				"refusing to start: auth disabled on non-loopback bind %s; set CLERK_SECRET_KEY or ALLOW_INSECURE_NO_AUTH=1",
				s.cfg.Host,
			)
		}
		log.Warn().Msg("clerk auth disabled on /api and /ws (CLERK_SECRET_KEY not set)")
	}

	s.router.Get("/health", s.handleHealth)
	s.router.Get("/ready", s.handleReady)
	s.router.Get("/metrics", s.handleMetricsProxy)
	s.router.Get("/ws", func(w http.ResponseWriter, r *http.Request) {
		ServeWs(s.hub, verifier, authEnabled, s.cfg.AllowedOrigins, w, r)
	})
	s.router.Get("/ws/audio", func(w http.ResponseWriter, r *http.Request) {
		ServeAudioWs(s.hub, verifier, authEnabled, s.cfg.AllowedOrigins, w, r)
	})

	cogClient := cognition.NewWithLogger(s.pythonURL+"/api/cognition", s.workingMemory, log.Logger)
	cogClient.SetInternalAuthSecret(s.cfg.InternalAuthSecret)
	cogHandler := cognition.NewHandler(cogClient, s.registry, log.Logger)

	ttsClient := tts.New(s.cfg.ElevenLabsKey, s.cfg.ElevenLabsVoiceID)
	ttsClient.SetPythonURL(s.pythonURL + "/api/tts")
	ttsClient.SetInternalAuthSecret(s.cfg.InternalAuthSecret)
	ttsHandler := tts.NewHandler(ttsClient)

	rl := newRateLimiter(
		s.cfg.RateLimitRPS, s.cfg.RateLimitBurst,
		s.cfg.RateLimitGlobalRPS, s.cfg.RateLimitGlobalBurst,
	)
	rl.start(ctx)

	s.router.Route("/api", func(r chi.Router) {
		r.Use(corsMiddleware(s.cfg.AllowedOrigins))
		r.Use(auth.RequireAuth(verifier, authEnabled))

		// Paid endpoints: rate-limited per authenticated caller (or IP) with a
		// global ceiling. Auth runs first so OwnerFromContext keys the bucket.
		r.Group(func(r chi.Router) {
			r.Use(rl.Middleware)
			r.Post("/cognition", cogHandler.ServeHTTP)
			r.Post("/tts", ttsHandler.ServeHTTP)
		})

		r.Get("/memory/working", s.handleWorkingMemory)
		r.Get("/memory/profile", s.handleMemoryProfileProxy)
		r.Get("/anchors", s.handleAnchorsProxy)
		r.Delete("/anchors/{anchor_id}", s.handleAnchorDeleteProxy)
	})

	// Wait (bounded, non-fatal) for FastAPI so the first cognition/tts request
	// does not fail with a connection-refused 500 during startup.
	if waitForPython(ctx, s.httpClient, s.pythonURL+"/health", pythonReadyRetries, pythonReadyInterval) {
		log.Info().Msg("FastAPI service ready")
	} else {
		log.Warn().Msg("FastAPI not ready, serving anyway")
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info().Str("addr", s.cfg.Addr()).Msg("http server listening")
		if err := s.httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			errCh <- err
		}
	}()

	// Shutdown is orchestrated by GracefulShutdown once ctx is cancelled; here we
	// just stop blocking so the caller can return.
	select {
	case <-ctx.Done():
		return nil
	case err := <-errCh:
		return err
	}
}

// Shutdown gracefully stops the HTTP server, refusing new connections and
// draining in-flight requests, bounded by ctx.
func (s *Server) Shutdown(ctx context.Context) error {
	if s.httpServer == nil {
		return nil
	}
	log.Info().Msg("shutting down http server")
	return s.httpServer.Shutdown(ctx)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{
		"status":  "ok",
		"version": "0.1.0",
	})
}

func (s *Server) handleWorkingMemory(w http.ResponseWriter, r *http.Request) {
	entries := s.workingMemory.All(auth.OwnerFromContext(r.Context()))
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(entries)
}

func (s *Server) handleMemoryProfileProxy(w http.ResponseWriter, r *http.Request) {
	s.proxyToPython(w, r, http.MethodGet, "/api/memory/profile")
}

func (s *Server) handleAnchorsProxy(w http.ResponseWriter, r *http.Request) {
	s.proxyToPython(w, r, http.MethodGet, "/api/anchors")
}

func (s *Server) handleAnchorDeleteProxy(w http.ResponseWriter, r *http.Request) {
	anchorID := chi.URLParam(r, "anchor_id")
	s.proxyToPython(w, r, http.MethodDelete, "/api/anchors/"+anchorID)
}

// proxyToPython forwards the inbound request to the internal Python service at
// path (relative to the Python base URL) using method, attaching the
// authenticated owner, the internal-auth secret, and the request id. It streams
// the upstream status and JSON body straight back to the caller.
func (s *Server) proxyToPython(w http.ResponseWriter, r *http.Request, method, path string) {
	req, err := http.NewRequestWithContext(r.Context(), method, s.pythonURL+path, nil)
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	setOwnerHeader(req, r)
	auth.SetInternalAuth(req, s.cfg.InternalAuthSecret)
	reqid.SetHeader(req, r.Context())
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

const (
	pythonReadyRetries  = 10
	pythonReadyInterval = 500 * time.Millisecond
)

// waitForPython polls healthURL until it returns 200 or the retry budget is spent.
// It never blocks longer than retries*interval and is non-fatal: a false return
// means "FastAPI is not confirmed ready, proceed anyway".
func waitForPython(ctx context.Context, client *http.Client, healthURL string, retries int, interval time.Duration) bool {
	for i := 0; i < retries; i++ {
		if req, err := http.NewRequestWithContext(ctx, http.MethodGet, healthURL, nil); err == nil {
			if resp, err := client.Do(req); err == nil {
				resp.Body.Close()
				if resp.StatusCode == http.StatusOK {
					return true
				}
			}
		}
		select {
		case <-ctx.Done():
			return false
		case <-time.After(interval):
		}
	}
	return false
}

// isLoopback reports whether host is a loopback (or unset) bind address, i.e. one
// that is not reachable from other machines.
func isLoopback(host string) bool {
	switch host {
	case "127.0.0.1", "localhost", "::1", "":
		return true
	default:
		return false
	}
}

// setOwnerHeader copies the authenticated owner from the inbound request context
// onto the outbound request to the internal Python service.
func setOwnerHeader(out, in *http.Request) {
	if owner := auth.OwnerFromContext(in.Context()); owner != "" {
		out.Header.Set(auth.OwnerHeader, owner)
	}
}

// corsMiddleware builds a CORS middleware for /api/* routes that reflects the
// request Origin only when it is in the allowed set. Requests from other origins
// receive no Access-Control-Allow-Origin header. The OPTIONS preflight is
// short-circuited with 204.
func corsMiddleware(allowedOrigins []string) func(http.Handler) http.Handler {
	allowed := make(map[string]struct{}, len(allowedOrigins))
	for _, o := range allowedOrigins {
		allowed[o] = struct{}{}
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if origin := r.Header.Get("Origin"); origin != "" {
				if _, ok := allowed[origin]; ok {
					w.Header().Set("Access-Control-Allow-Origin", origin)
					w.Header().Add("Vary", "Origin")
				}
			}
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

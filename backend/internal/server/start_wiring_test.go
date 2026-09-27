package server

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// SECURITY-MIDDLE-2 — Start derives (verifier, authEnabled) from the config and
// hands them to routes(). Every router-level test calls routes() directly with
// arguments it chose, so `s.routes(ctx, verifier, false)` in Start (every
// /api, /ws and /ws/audio route unauthenticated while Clerk is configured,
// /health still green) passed the whole suite.
//
// This runs the real Start with a Clerk key on a loopback port and checks the
// router it actually serves from outside.
func TestStart_ClerkConfiguredServesAnAuthenticatedRouter(t *testing.T) {
	var pythonHits atomic.Int64
	python := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health" {
			w.WriteHeader(http.StatusOK)
			return
		}
		pythonHits.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer python.Close()

	base := startOnLoopback(t, &config.Config{
		// Only the key's presence matters: no request here carries a token, so
		// the verifier never makes a network call.
		ClerkSecretKey:       "sk_test_placeholder_not_a_real_key",
		MetricsToken:         testMetricsToken,
		PythonBaseURL:        python.URL,
		RateLimitRPS:         100,
		RateLimitBurst:       100,
		RateLimitGlobalRPS:   100,
		RateLimitGlobalBurst: 100,
	})

	for _, rt := range protectedRoutes {
		req, err := http.NewRequest(rt.method, base+rt.path, nil)
		if err != nil {
			t.Fatalf("request %s %s: %v", rt.method, rt.path, err)
		}
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("%s %s: %v", rt.method, rt.path, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Errorf("%s %s = %d without a credential through the real Start, want 401",
				rt.method, rt.path, resp.StatusCode)
		}
	}
	if n := pythonHits.Load(); n != 0 {
		t.Fatalf("%d unauthenticated request(s) reached Python through the real Start", n)
	}

	resp, err := http.Get(base + "/health")
	if err != nil {
		t.Fatalf("get /health: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/health = %d, want 200 with Clerk configured", resp.StatusCode)
	}
}

// protectedRoutes is every route that must refuse a caller with no user
// credential. The WebSocket routes answer 401 before any upgrade.
var protectedRoutes = []struct{ method, path string }{
	{http.MethodPost, "/api/cognition"},
	{http.MethodPost, "/api/tts"},
	{http.MethodGet, "/api/memory/working"},
	{http.MethodGet, "/api/memory/profile"},
	{http.MethodGet, "/api/memory/episodic"},
	{http.MethodGet, "/api/memory/export"},
	{http.MethodDelete, "/api/memory"},
	{http.MethodDelete, "/api/memory/0123456789abcdef"},
	{http.MethodGet, "/api/anchors"},
	{http.MethodDelete, "/api/anchors/anchor-1"},
	{http.MethodGet, "/ws"},
	{http.MethodGet, "/ws/audio"},
}

// startOnLoopback runs the real Start on a free 127.0.0.1 port and returns the
// base URL once /health answers. The listener is loopback-only, and the server
// is shut down when the test ends. The port is reserved and released before
// Start binds it, so if something else takes it in between, Start returns the
// bind error and this retries on a fresh port.
func startOnLoopback(t *testing.T, cfg *config.Config) string {
	t.Helper()
	cfg.Host = "127.0.0.1"
	for attempt := 1; ; attempt++ {
		cfg.Port = freeLoopbackPort(t)
		base, err := startOnce(t, cfg)
		if err == nil {
			return base
		}
		if attempt == 3 {
			t.Fatalf("Start never served /health on a loopback port: %v", err)
		}
	}
}

func startOnce(t *testing.T, cfg *config.Config) (string, error) {
	t.Helper()
	s := New(cfg, NewHub(), memory.New(5))
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() { done <- s.Start(ctx) }()
	stop := func() {
		cancel()
		shutdownCtx, stopShutdown := context.WithTimeout(context.Background(), 5*time.Second)
		defer stopShutdown()
		_ = s.Shutdown(shutdownCtx)
	}

	base := fmt.Sprintf("http://127.0.0.1:%d", cfg.Port)
	deadline := time.Now().Add(10 * time.Second)
	for {
		select {
		case err := <-done:
			stop()
			return "", fmt.Errorf("start on %s returned early: %v", base, err)
		default:
		}
		resp, err := http.Get(base + "/health")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				t.Cleanup(func() {
					stop()
					<-done
				})
				return base, nil
			}
		}
		if time.Now().After(deadline) {
			stop()
			<-done
			return "", fmt.Errorf("no /health on %s within 10s (last error: %v)", base, err)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

func freeLoopbackPort(t *testing.T) int {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("reserve a loopback port: %v", err)
	}
	defer l.Close()
	return l.Addr().(*net.TCPAddr).Port
}

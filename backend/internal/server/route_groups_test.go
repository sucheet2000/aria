package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

// F3 — which group a route sits in is a security property, and routes() says
// so in its own comment. Nothing checked it.
//
// Six mutations through that seam all passed the whole suite: deleting
// RequireAuth, deleting corsMiddleware, deleting the rate limiter, deleting the
// request-id middleware, moving /api/memory/working to a bare top-level route,
// and wrapping the routes() call itself in `if false`. The only router-level
// tests ran with authEnabled=false, so they could not have caught any of it.
//
// This drives the real router with auth ENABLED and asserts the boundary from
// outside, which is the only place the grouping is observable.

// stubVerifier lives in proxy_test.go and accepts any token, which makes the
// metrics assertion below stronger: Clerk would have said yes.

func newRoutedServer(t *testing.T) *httptest.Server {
	t.Helper()
	s := newMetricsServer("http://127.0.0.1:1", testMetricsToken)
	s.routes(context.Background(), stubVerifier{owner: "user_1"}, true)
	edge := httptest.NewServer(s.router)
	t.Cleanup(edge.Close)
	return edge
}

func TestRouteGroups_ProtectedRoutesRequireAuth(t *testing.T) {
	edge := newRoutedServer(t)

	// Every /api route must refuse an unauthenticated caller. A route that
	// slipped out of the group would answer instead — possibly proxying to
	// Python with a default owner.
	for _, path := range []string{
		"/api/memory/working",
		"/api/anchors",
	} {
		resp, err := http.Get(edge.URL + path)
		if err != nil {
			t.Fatalf("get %s: %v", path, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Fatalf("%s = %d without a credential, want 401", path, resp.StatusCode)
		}
	}

	for _, path := range []string{"/api/cognition", "/api/tts"} {
		resp, err := http.Post(edge.URL+path, "application/json", http.NoBody)
		if err != nil {
			t.Fatalf("post %s: %v", path, err)
		}
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Fatalf("%s = %d without a credential, want 401", path, resp.StatusCode)
		}
	}
}

func TestRouteGroups_ProbesStayOpen(t *testing.T) {
	edge := newRoutedServer(t)

	// Railway probes /health; it must never need a credential.
	resp, err := http.Get(edge.URL + "/health")
	if err != nil {
		t.Fatalf("get /health: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/health = %d without a credential, want 200", resp.StatusCode)
	}
}

// And /metrics carries its own credential rather than Clerk's, even with Clerk
// enabled — the auth-domain separation, asserted through the real router.
func TestRouteGroups_MetricsUsesItsOwnCredential(t *testing.T) {
	edge := newRoutedServer(t)

	req, _ := http.NewRequest(http.MethodGet, edge.URL+"/metrics", nil)
	req.Header.Set("Authorization", "Bearer good-token") // a valid USER token
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("get /metrics: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("/metrics = %d with a valid user token, want 401", resp.StatusCode)
	}
}

// G2 — CORS is part of the same group membership. Deleting corsMiddleware left
// the auth assertions above green, because they never look at the headers.
func TestRouteGroups_ApiReflectsOnlyAllowedOrigins(t *testing.T) {
	s := newMetricsServer("http://127.0.0.1:1", testMetricsToken)
	s.cfg.AllowedOrigins = []string{"http://localhost:3000"}
	s.routes(context.Background(), stubVerifier{owner: "user_1"}, true)
	edge := httptest.NewServer(s.router)
	defer edge.Close()

	allowed, err := http.NewRequest(http.MethodOptions, edge.URL+"/api/anchors", nil)
	if err != nil {
		t.Fatalf("request: %v", err)
	}
	allowed.Header.Set("Origin", "http://localhost:3000")
	resp, err := http.DefaultClient.Do(allowed)
	if err != nil {
		t.Fatalf("options: %v", err)
	}
	resp.Body.Close()
	if got := resp.Header.Get("Access-Control-Allow-Origin"); got != "http://localhost:3000" {
		t.Fatalf("allowed origin not reflected: %q — is corsMiddleware still on the group?", got)
	}

	// And a foreign origin is never reflected.
	foreign, _ := http.NewRequest(http.MethodOptions, edge.URL+"/api/anchors", nil)
	foreign.Header.Set("Origin", "https://evil.test")
	resp2, err := http.DefaultClient.Do(foreign)
	if err != nil {
		t.Fatalf("options: %v", err)
	}
	resp2.Body.Close()
	if got := resp2.Header.Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("reflected a foreign origin: %q", got)
	}
}

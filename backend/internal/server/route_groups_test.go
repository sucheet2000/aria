package server

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"github.com/gorilla/websocket"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/config"
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
//
// A 401 on its own proves nothing about a route: RequireAuth wraps the whole
// /api subrouter, so it answers 401 for a path that is not registered at all.
// Route existence is therefore asserted with authenticated requests, which must
// reach their own handler with the verified owner.

// stubVerifier lives in proxy_test.go and accepts any token, which makes the
// metrics assertion below stronger: Clerk would have said yes.

const routeTestOwner = "user_1"

// upstreamCall is one request the fake Python received from the edge.
type upstreamCall struct {
	method string
	target string
	owner  string
}

// recordingPython is a fake Python that records every non-probe request and
// answers each path the way the real service would, closely enough for the
// edge to relay it.
type recordingPython struct {
	*httptest.Server
	mu    sync.Mutex
	calls []upstreamCall
}

func newRecordingPython(t *testing.T) *recordingPython {
	t.Helper()
	rp := &recordingPython{}
	rp.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/health", "/ready":
			w.WriteHeader(http.StatusOK)
			return
		}
		rp.mu.Lock()
		rp.calls = append(rp.calls, upstreamCall{r.Method, r.URL.RequestURI(), r.Header.Get(auth.OwnerHeader)})
		rp.mu.Unlock()
		switch r.URL.Path {
		case "/api/tts":
			w.Header().Set("Content-Type", "audio/mpeg")
			_, _ = w.Write([]byte("fake-mp3-bytes"))
		case "/api/cognition":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"natural_language_response":"ok","symbolic_inference":"","avatar_emotion":"neutral","processing_ms":1}`))
		default:
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{}`))
		}
	}))
	t.Cleanup(rp.Close)
	return rp
}

func (rp *recordingPython) take() []upstreamCall {
	rp.mu.Lock()
	defer rp.mu.Unlock()
	calls := rp.calls
	rp.calls = nil
	return calls
}

// newAuthRoutedServer builds the production router with auth enabled in front
// of pythonURL. mutate adjusts the config before routes() reads it.
func newAuthRoutedServer(t *testing.T, pythonURL string, verifier auth.Verifier, mutate func(*config.Config)) (*Server, *httptest.Server) {
	t.Helper()
	s := newMetricsServer(pythonURL, testMetricsToken)
	s.cfg.RateLimitRPS = 1000
	s.cfg.RateLimitBurst = 1000
	s.cfg.RateLimitGlobalRPS = 1000
	s.cfg.RateLimitGlobalBurst = 1000
	if mutate != nil {
		mutate(s.cfg)
	}
	// t.Context() stops the limiter's sweep goroutine when the test ends.
	s.routes(t.Context(), verifier, true)
	edge := httptest.NewServer(s.router)
	t.Cleanup(edge.Close)
	return s, edge
}

func edgeRequest(t *testing.T, method, url, body, bearer string) *http.Response {
	t.Helper()
	req, err := http.NewRequest(method, url, strings.NewReader(body))
	if err != nil {
		t.Fatalf("request %s %s: %v", method, url, err)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("%s %s: %v", method, url, err)
	}
	return resp
}

func TestRouteGroups_ProtectedRoutesRequireAuth(t *testing.T) {
	python := newRecordingPython(t)
	_, edge := newAuthRoutedServer(t, python.URL, stubVerifier{owner: routeTestOwner}, nil)

	// Every protected route must refuse an unauthenticated caller. A route that
	// slipped out of the group would answer instead, possibly proxying to
	// Python with a default owner.
	for _, rt := range protectedRoutes {
		resp := edgeRequest(t, rt.method, edge.URL+rt.path, "", "")
		resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Errorf("%s %s = %d without a credential, want 401", rt.method, rt.path, resp.StatusCode)
		}
	}
	if calls := python.take(); len(calls) != 0 {
		t.Fatalf("unauthenticated requests reached Python: %+v", calls)
	}
}

func TestRouteGroups_ProbesStayOpen(t *testing.T) {
	python := newRecordingPython(t)
	_, edge := newAuthRoutedServer(t, python.URL, stubVerifier{owner: routeTestOwner}, nil)

	// Railway probes /health, and /ready is the readiness probe; neither may
	// ever need a credential.
	for _, path := range []string{"/health", "/ready"} {
		resp := edgeRequest(t, http.MethodGet, edge.URL+path, "", "")
		resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("%s = %d without a credential, want 200", path, resp.StatusCode)
		}
	}
}

// And /metrics carries its own credential rather than Clerk's, even with Clerk
// enabled — the auth-domain separation, asserted through the real router.
func TestRouteGroups_MetricsUsesItsOwnCredential(t *testing.T) {
	up := upstream(t, http.StatusOK, "application/json", `{"errors":0}`)
	_, edge := newAuthRoutedServer(t, up.URL, stubVerifier{owner: routeTestOwner}, nil)

	for _, tc := range []struct {
		name, bearer string
		want         int
	}{
		{"no credential", "", http.StatusUnauthorized},
		{"a valid USER token", "good-token", http.StatusUnauthorized},
		{"the metrics token", testMetricsToken, http.StatusOK},
	} {
		resp := edgeRequest(t, http.MethodGet, edge.URL+"/metrics", "", tc.bearer)
		resp.Body.Close()
		if resp.StatusCode != tc.want {
			t.Fatalf("/metrics with %s = %d, want %d", tc.name, resp.StatusCode, tc.want)
		}
	}
}

// G2 — CORS is part of the same group membership. Deleting corsMiddleware left
// the auth assertions above green, because they never look at the headers.
func TestRouteGroups_ApiReflectsOnlyAllowedOrigins(t *testing.T) {
	s := newMetricsServer("http://127.0.0.1:1", testMetricsToken)
	s.cfg.AllowedOrigins = []string{"http://localhost:3000"}
	s.routes(t.Context(), stubVerifier{owner: "user_1"}, true)
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

// B23 — every /api route is registered, reaches its own handler, and carries
// the verified owner. Deleting a registration turns its row into a 404/405;
// moving it out of the auth group loses the owner.
func TestRouteGroups_EveryApiRouteReachesItsHandlerForTheVerifiedOwner(t *testing.T) {
	python := newRecordingPython(t)
	s, edge := newAuthRoutedServer(t, python.URL, stubVerifier{owner: routeTestOwner}, nil)
	s.workingMemory.Push(routeTestOwner, "owner-scoped-inference")

	cases := []struct {
		method, path, body string
		upstream           string // "" for the Go-local working-memory handler
	}{
		{http.MethodPost, "/api/cognition", `{"message":"hi","session_id":"s1"}`, "POST /api/cognition"},
		{http.MethodPost, "/api/tts", `{"text":"hi"}`, "POST /api/tts"},
		{http.MethodGet, "/api/memory/working", "", ""},
		{http.MethodGet, "/api/memory/profile", "", "GET /api/memory/profile"},
		{http.MethodGet, "/api/memory/episodic", "", "GET /api/memory/episodic"},
		{http.MethodGet, "/api/memory/export?offset=0", "", "GET /api/memory/export?offset=0"},
		{http.MethodDelete, "/api/memory", "", "DELETE /api/memory"},
		{http.MethodDelete, "/api/memory/0123456789abcdef", "", "DELETE /api/memory/0123456789abcdef"},
		{http.MethodGet, "/api/anchors", "", "GET /api/anchors"},
		{http.MethodDelete, "/api/anchors/anchor-1", "", "DELETE /api/anchors/anchor-1"},
	}
	for _, tc := range cases {
		resp := edgeRequest(t, tc.method, edge.URL+tc.path, tc.body, "good-token")
		body, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != http.StatusOK {
			t.Errorf("%s %s = %d for an authenticated caller, want 200 (is the route registered?)",
				tc.method, tc.path, resp.StatusCode)
			python.take()
			continue
		}
		calls := python.take()
		if tc.upstream == "" {
			if len(calls) != 0 {
				t.Errorf("%s %s should be served by Go, but reached Python: %+v", tc.method, tc.path, calls)
			}
			if !strings.Contains(string(body), "owner-scoped-inference") {
				t.Errorf("%s %s did not return the verified owner's working memory: %q", tc.method, tc.path, body)
			}
			continue
		}
		want := upstreamCall{
			method: strings.SplitN(tc.upstream, " ", 2)[0],
			target: strings.SplitN(tc.upstream, " ", 2)[1],
			owner:  routeTestOwner,
		}
		if len(calls) != 1 || calls[0] != want {
			t.Errorf("%s %s reached Python as %+v, want exactly [%+v]", tc.method, tc.path, calls, want)
		}
	}
}

// The WebSocket routes exist and upgrade for an authenticated caller. The 401
// assertions above would still pass if either registration were deleted.
func TestRouteGroups_WebSocketRoutesUpgradeForAnAuthenticatedCaller(t *testing.T) {
	s, edge := newAuthRoutedServer(t, "http://127.0.0.1:1", stubVerifier{owner: routeTestOwner}, nil)
	// Without a running hub, ServeWs blocks forever registering the client.
	go s.hub.Run(t.Context())
	wsBase := "ws" + strings.TrimPrefix(edge.URL, "http")

	for _, path := range []string{"/ws", "/ws/audio"} {
		dialer := *websocket.DefaultDialer
		dialer.Subprotocols = []string{"aria-ws", "good-token"}
		conn, resp, err := dialer.Dial(wsBase+path, nil)
		if err != nil {
			status := 0
			if resp != nil {
				status = resp.StatusCode
			}
			t.Fatalf("%s did not upgrade for an authenticated caller (status %d): %v", path, status, err)
		}
		conn.Close()
	}
}

// RATE-LIMIT-PIN — the limiter is tested on its own in ratelimit_test.go, but
// nothing proved production attaches it: deleting either r.Use(rl.Middleware)
// left the suite green.
//
// Each case gets a fresh production router whose per-owner bucket holds one
// request and never refills during the test, so the wiring is observable from
// outside: one owner's second request is refused before it reaches Python,
// another owner still gets through (the bucket is keyed by the verified owner,
// so auth ran first), and unauthenticated callers are always turned away by
// auth, never by the limiter.
func TestRouteGroups_LimitedRoutesAreRateLimitedPerVerifiedOwner(t *testing.T) {
	limited := []struct {
		name, method, path, body, upstream string
	}{
		{"paid: cognition", http.MethodPost, "/api/cognition", `{"message":"hi","session_id":"s1"}`, "/api/cognition"},
		{"paid: tts", http.MethodPost, "/api/tts", `{"text":"hi"}`, "/api/tts"},
		{"data control: export", http.MethodGet, "/api/memory/export", "", "/api/memory/export"},
		{"data control: delete all", http.MethodDelete, "/api/memory", "", "/api/memory"},
		{"data control: delete one", http.MethodDelete, "/api/memory/0123456789abcdef", "", "/api/memory/0123456789abcdef"},
	}
	verifier := ownerVerifier{"tok-a": "owner-a", "tok-b": "owner-b"}

	for _, rt := range limited {
		t.Run(rt.name, func(t *testing.T) {
			python := newRecordingPython(t)
			_, edge := newAuthRoutedServer(t, python.URL, verifier, func(c *config.Config) {
				c.RateLimitRPS = 1e-9
				c.RateLimitBurst = 1
			})

			for i := 0; i < 3; i++ {
				resp := edgeRequest(t, rt.method, edge.URL+rt.path, rt.body, "")
				resp.Body.Close()
				if resp.StatusCode != http.StatusUnauthorized {
					t.Fatalf("unauthenticated request %d = %d, want 401 from auth (the limiter must not run before auth)",
						i+1, resp.StatusCode)
				}
			}

			first := edgeRequest(t, rt.method, edge.URL+rt.path, rt.body, "tok-a")
			first.Body.Close()
			if first.StatusCode == http.StatusTooManyRequests {
				t.Fatalf("owner-a's first request was rate limited")
			}
			if calls := python.take(); len(calls) != 1 || calls[0].owner != "owner-a" || !strings.HasPrefix(calls[0].target, rt.upstream) {
				t.Fatalf("owner-a's first request did not reach its handler: %+v", calls)
			}

			second := edgeRequest(t, rt.method, edge.URL+rt.path, rt.body, "tok-a")
			second.Body.Close()
			if second.StatusCode != http.StatusTooManyRequests {
				t.Fatalf("owner-a's second request = %d, want 429: is rl.Middleware still attached to %s?",
					second.StatusCode, rt.path)
			}
			if calls := python.take(); len(calls) != 0 {
				t.Fatalf("a rate-limited request still reached Python: %+v", calls)
			}

			other := edgeRequest(t, rt.method, edge.URL+rt.path, rt.body, "tok-b")
			other.Body.Close()
			if other.StatusCode == http.StatusTooManyRequests {
				t.Fatalf("owner-b was limited by owner-a's bucket: the limiter is not keyed by the verified owner")
			}
			if calls := python.take(); len(calls) != 1 || calls[0].owner != "owner-b" {
				t.Fatalf("owner-b's request did not reach its handler as owner-b: %+v", calls)
			}
		})
	}
}

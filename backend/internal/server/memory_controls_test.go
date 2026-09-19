package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// mountMemoryRoutes mirrors the production /api mount for the S3 memory
// routes: Clerk auth first, then the owner-scoped proxies.
func mountMemoryRoutes(s *Server, verifier auth.Verifier, authEnabled bool) *chi.Mux {
	router := chi.NewRouter()
	router.Route("/api", func(r chi.Router) {
		r.Use(auth.RequireAuth(verifier, authEnabled))
		r.Get("/memory/export", s.handleMemoryExportProxy)
		r.Delete("/memory", s.handleMemoryDeleteAll)
		r.Delete("/memory/{entry_id}", s.handleMemoryDeleteEntryProxy)
	})
	return router
}

// Test 7: without a valid token every memory-control route is rejected before
// anything reaches Python.
func TestMemoryRoutes_Unauthenticated_401(t *testing.T) {
	pythonHit := false
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		pythonHit = true
		w.Write([]byte(`{}`))
	}))
	defer fakePython.Close()
	s := newTestServer(fakePython.URL)
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_9"}, true)

	for _, tc := range []struct{ method, path string }{
		{http.MethodGet, "/api/memory/export"},
		{http.MethodDelete, "/api/memory"},
		{http.MethodDelete, "/api/memory/abc"},
	} {
		req := httptest.NewRequest(tc.method, tc.path, nil) // no Authorization header
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)
		if rec.Code != http.StatusUnauthorized {
			t.Errorf("%s %s: status = %d, want 401", tc.method, tc.path, rec.Code)
		}
	}
	if pythonHit {
		t.Fatal("unauthenticated request reached the Python service")
	}
}

// Test 8 (edge): the verified owner is forwarded; a client-supplied owner in
// the query string never reaches Python (the proxy forwards path only).
func TestMemoryRoutes_ForwardVerifiedOwnerOnly(t *testing.T) {
	for _, tc := range []struct {
		name, method, path, wantPath string
	}{
		{"export", http.MethodGet, "/api/memory/export?owner=owner_a", "/api/memory/export"},
		{"delete all", http.MethodDelete, "/api/memory?owner=owner_a", "/api/memory"},
		{"delete entry", http.MethodDelete, "/api/memory/0123456789abcdef?owner=owner_a", "/api/memory/0123456789abcdef"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var gotOwner, gotSecret, gotURL string
			fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				gotOwner = r.Header.Get("X-Aria-Owner")
				gotSecret = r.Header.Get("X-Internal-Auth")
				gotURL = r.URL.String()
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`{"deleted":{"profile":0,"episodic":0,"working":0}}`))
			}))
			defer fakePython.Close()
			s := newTestServer(fakePython.URL)
			s.cfg.InternalAuthSecret = "s3cret"
			router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)

			req := httptest.NewRequest(tc.method, tc.path, strings.NewReader(`{"owner":"owner_a"}`))
			req.Header.Set("Authorization", "Bearer tok")
			rec := httptest.NewRecorder()
			router.ServeHTTP(rec, req)

			if rec.Code != http.StatusOK {
				t.Fatalf("status = %d, want 200; body %s", rec.Code, rec.Body.String())
			}
			if gotOwner != "owner_b" {
				t.Errorf("X-Aria-Owner = %q, want the verified owner_b", gotOwner)
			}
			if gotSecret != "s3cret" {
				t.Errorf("X-Internal-Auth = %q, want s3cret", gotSecret)
			}
			if gotURL != tc.wantPath {
				t.Errorf("python saw %q, want %q (client query string must not be forwarded)", gotURL, tc.wantPath)
			}
		})
	}
}

// Test 11 (Go side): delete-all also clears the owner's Go working-memory
// ring, and only that owner's.
func TestMemoryDeleteAll_ClearsGoWorkingMemoryForOwnerOnly(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"deleted":{"profile":2,"episodic":1,"working":0}}`))
	}))
	defer fakePython.Close()
	s := newTestServer(fakePython.URL)
	s.workingMemory.Push("owner_b", "b is focused")
	s.workingMemory.Push("owner_a", "a is stuck")
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)

	req := httptest.NewRequest(http.MethodDelete, "/api/memory", nil)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), `"profile":2`) {
		t.Errorf("python delete counts not propagated: %s", rec.Body.String())
	}
	if got := s.workingMemory.All("owner_b"); len(got) != 0 {
		t.Errorf("owner_b working memory not cleared: %v", got)
	}
	if got := s.workingMemory.All("owner_a"); len(got) != 1 {
		t.Errorf("owner_a working memory touched: %v", got)
	}
}

// If Python refuses the delete, Go must not report success and must keep its
// own state (nothing was deleted anywhere).
func TestMemoryDeleteAll_PythonFailureKeepsGoState(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		w.Write([]byte(`{"detail":"memory store unavailable"}`))
	}))
	defer fakePython.Close()
	s := newTestServer(fakePython.URL)
	s.workingMemory.Push("owner_b", "b is focused")
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)

	req := httptest.NewRequest(http.MethodDelete, "/api/memory", nil)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 propagated", rec.Code)
	}
	if got := s.workingMemory.All("owner_b"); len(got) != 1 {
		t.Errorf("Go working memory cleared despite upstream failure: %v", got)
	}
}

// Test 12 (edge): Python down → 502, not a hang or a 200.
func TestMemoryRoutes_PythonDown_502(t *testing.T) {
	s := newTestServer("http://127.0.0.1:1") // nothing listens here
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)
	req := httptest.NewRequest(http.MethodGet, "/api/memory/export", nil)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

// Response-size bound: an oversized upstream body is refused as 502 rather
// than relayed truncated (which would be a 200 with invalid JSON).
func TestProxyToPython_OversizedBodyIs502(t *testing.T) {
	big := strings.Repeat("x", maxProxyResponseBytes+1024)
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(big))
	}))
	defer fakePython.Close()
	s := newTestServer(fakePython.URL)
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)
	req := httptest.NewRequest(http.MethodGet, "/api/memory/export", nil)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502 for an over-cap upstream body", rec.Code)
	}
	if rec.Body.Len() > maxProxyResponseBytes {
		t.Fatalf("relayed %d bytes, want at most %d", rec.Body.Len(), maxProxyResponseBytes)
	}
}

// A memory entry id is a 16-hex content hash; anything else is rejected at
// the edge before it can become part of an upstream path.
func TestMemoryDeleteEntry_RejectsMalformedID(t *testing.T) {
	pythonHit := false
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		pythonHit = true
		w.Write([]byte(`{}`))
	}))
	defer fakePython.Close()
	s := newTestServer(fakePython.URL)
	router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)
	for _, id := range []string{"abc", "ZZZZZZZZZZZZZZZZ", "0123456789abcdef0", "..%2f"} {
		req := httptest.NewRequest(http.MethodDelete, "/api/memory/"+id, nil)
		req.Header.Set("Authorization", "Bearer tok")
		rec := httptest.NewRecorder()
		router.ServeHTTP(rec, req)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("id %q: status = %d, want 400", id, rec.Code)
		}
	}
	if pythonHit {
		t.Fatal("malformed id reached Python")
	}
	req := httptest.NewRequest(http.MethodDelete, "/api/memory/0123456789abcdef", nil)
	req.Header.Set("Authorization", "Bearer tok")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || !pythonHit {
		t.Fatalf("well-formed id: status = %d, python hit = %v", rec.Code, pythonHit)
	}
}

// Export paging: only a validated non-negative integer `offset` is forwarded;
// anything else in the client query string is dropped or rejected.
func TestMemoryExportProxy_ForwardsValidatedOffsetOnly(t *testing.T) {
	for _, tc := range []struct {
		query    string
		wantCode int
		wantURL  string
	}{
		{"", http.StatusOK, "/api/memory/export"},
		{"?offset=500", http.StatusOK, "/api/memory/export?offset=500"},
		{"?owner=owner_a&offset=7", http.StatusOK, "/api/memory/export?offset=7"},
		{"?offset=abc", http.StatusBadRequest, ""},
		{"?offset=-1", http.StatusBadRequest, ""},
		{"?offset=99999999999", http.StatusBadRequest, ""},
	} {
		t.Run(tc.query, func(t *testing.T) {
			var gotURL string
			hit := false
			fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				hit = true
				gotURL = r.URL.String()
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`{"profile":[],"episodic":[],"working":[],"truncated":[]}`))
			}))
			defer fakePython.Close()
			s := newTestServer(fakePython.URL)
			router := mountMemoryRoutes(s, stubVerifier{owner: "owner_b"}, true)
			req := httptest.NewRequest(http.MethodGet, "/api/memory/export"+tc.query, nil)
			req.Header.Set("Authorization", "Bearer tok")
			rec := httptest.NewRecorder()
			router.ServeHTTP(rec, req)
			if rec.Code != tc.wantCode {
				t.Fatalf("status = %d, want %d", rec.Code, tc.wantCode)
			}
			if tc.wantCode == http.StatusOK && gotURL != tc.wantURL {
				t.Errorf("python saw %q, want %q", gotURL, tc.wantURL)
			}
			if tc.wantCode != http.StatusOK && hit {
				t.Error("invalid offset reached Python")
			}
		})
	}
}

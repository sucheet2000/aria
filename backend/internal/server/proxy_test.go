package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

func newTestServer(pythonURL string) *Server {
	cfg := &config.Config{Port: 0}
	hub := NewHub(nil)
	wm := memory.New(5)
	s := New(cfg, hub, wm, nil)
	s.pythonURL = pythonURL
	s.httpClient = &http.Client{Timeout: 5 * time.Second}
	return s
}

func TestAnchorsProxy_Get(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/anchors" || r.Method != http.MethodGet {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"anchors":[{"anchor_id":"x1","label":"lamp","x":0.1,"y":0.2,"z":0.3}]}`))
	}))
	defer fakePython.Close()

	s := newTestServer(fakePython.URL)

	req := httptest.NewRequest(http.MethodGet, "/api/anchors", nil)
	rec := httptest.NewRecorder()
	s.handleAnchorsProxy(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	anchors, ok := body["anchors"].([]any)
	if !ok || len(anchors) == 0 {
		t.Fatalf("expected non-empty anchors array, got %v", body)
	}
	first := anchors[0].(map[string]any)
	if first["anchor_id"] != "x1" {
		t.Errorf("anchor_id = %v, want x1", first["anchor_id"])
	}
}

func TestAnchorsProxy_PythonDown(t *testing.T) {
	s := newTestServer("http://127.0.0.1:1") // nothing listening
	s.httpClient = &http.Client{Timeout: 200 * time.Millisecond}

	req := httptest.NewRequest(http.MethodGet, "/api/anchors", nil)
	rec := httptest.NewRecorder()
	s.handleAnchorsProxy(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

func TestAnchorDeleteProxy_OK(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodDelete || r.URL.Path != "/api/anchors/abc-123" {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"deleted":"abc-123"}`))
	}))
	defer fakePython.Close()

	s := newTestServer(fakePython.URL)

	// Use a chi router so URLParam works.
	r := chi.NewRouter()
	r.Delete("/api/anchors/{anchor_id}", s.handleAnchorDeleteProxy)

	req := httptest.NewRequest(http.MethodDelete, "/api/anchors/abc-123", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body: %s", rec.Code, rec.Body.String())
	}
	var body map[string]any
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if body["deleted"] != "abc-123" {
		t.Errorf("deleted = %v, want abc-123", body["deleted"])
	}
}

func TestAnchorDeleteProxy_NotFound(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		w.Write([]byte(`{"detail":"anchor not found"}`))
	}))
	defer fakePython.Close()

	s := newTestServer(fakePython.URL)

	r := chi.NewRouter()
	r.Delete("/api/anchors/{anchor_id}", s.handleAnchorDeleteProxy)

	req := httptest.NewRequest(http.MethodDelete, "/api/anchors/no-such-id", nil)
	rec := httptest.NewRecorder()
	r.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want 404", rec.Code)
	}
}

func TestCORSMiddleware_IncludesDelete(t *testing.T) {
	handler := corsMiddleware(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNoContent)
	}))

	req := httptest.NewRequest(http.MethodOptions, "/api/anchors/x", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	methods := rec.Header().Get("Access-Control-Allow-Methods")
	if !strings.Contains(methods, "DELETE") {
		t.Errorf("Access-Control-Allow-Methods = %q, expected DELETE to be present", methods)
	}
}

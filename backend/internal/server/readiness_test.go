package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestWaitForPython_ReadyReturnsTrue(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	if !waitForPython(context.Background(), ts.Client(), ts.URL+"/health", 5, 10*time.Millisecond) {
		t.Fatal("expected true when /health is reachable")
	}
}

func TestWaitForPython_UnreachableGivesUp(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := ts.URL
	ts.Close() // now unreachable — connection refused

	start := time.Now()
	if waitForPython(context.Background(), ts.Client(), url+"/health", 3, 10*time.Millisecond) {
		t.Fatal("expected false when /health is unreachable")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("gave up too slowly: %v", elapsed)
	}
}

func TestWaitForPython_CancelledContextReturnsFalse(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if waitForPython(ctx, http.DefaultClient, "http://127.0.0.1:0/health", 10, time.Second) {
		t.Fatal("expected false when context is already cancelled")
	}
}

func TestHandleReady_PythonUp_NoWorkers_200(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/ready" {
			http.Error(w, "unexpected path", http.StatusNotFound)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	rec := httptest.NewRecorder()
	s.handleReady(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body: %s", rec.Code, rec.Body.String())
	}
}

func TestHandleReady_PythonDown_503(t *testing.T) {
	s := newTestServer("http://127.0.0.1:1") // nothing listening
	s.httpClient = &http.Client{Timeout: 200 * time.Millisecond}

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	rec := httptest.NewRecorder()
	s.handleReady(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
}

func TestHandleReady_PythonNot200_503(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	rec := httptest.NewRecorder()
	s.handleReady(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503", rec.Code)
	}
}

func TestHandleReady_WorkerDown_503(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)
	s.AddReadyCheck("audio", func() bool { return false })

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	rec := httptest.NewRecorder()
	s.handleReady(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 when a worker is down", rec.Code)
	}
}

func TestHandleReady_ForwardsInternalAuth(t *testing.T) {
	var gotSecret string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Auth")
		w.WriteHeader(http.StatusOK)
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)
	s.cfg.InternalAuthSecret = "sekret"

	req := httptest.NewRequest(http.MethodGet, "/ready", nil)
	rec := httptest.NewRecorder()
	s.handleReady(rec, req)

	if gotSecret != "sekret" {
		t.Errorf("X-Internal-Auth forwarded to Python = %q, want sekret", gotSecret)
	}
}

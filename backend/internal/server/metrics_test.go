package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestHandleMetricsProxy_StreamsBody(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/metrics" || r.Method != http.MethodGet {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("aria_requests_total 42\n"))
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	s.handleMetricsProxy(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), "aria_requests_total 42") {
		t.Errorf("body = %q, want it to contain the upstream metrics", rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); !strings.Contains(ct, "text/plain") {
		t.Errorf("Content-Type = %q, want it to pass through text/plain", ct)
	}
}

func TestHandleMetricsProxy_ForwardsInternalAuth(t *testing.T) {
	var gotSecret string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Auth")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)
	s.cfg.InternalAuthSecret = "boundary-secret"

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	s.handleMetricsProxy(rec, req)

	if gotSecret != "boundary-secret" {
		t.Errorf("X-Internal-Auth = %q, want boundary-secret", gotSecret)
	}
}

func TestHandleMetricsProxy_PythonDown_502(t *testing.T) {
	s := newTestServer("http://127.0.0.1:1") // nothing listening
	s.httpClient = &http.Client{Timeout: 200 * time.Millisecond}

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	s.handleMetricsProxy(rec, req)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502", rec.Code)
	}
}

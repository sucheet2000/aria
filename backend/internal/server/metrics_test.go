package server

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// Re-aimed for M1. This test previously asserted the edge PASSED THROUGH an
// upstream "text/plain; version=0.0.4" — it pinned the very relay that let a
// non-metrics upstream response be served from ARIA's origin. It also described
// a Prometheus exposition format this service has never produced: the Python
// handler returns MetricsCollector().snapshot(), a dict rendered as JSON.
func TestHandleMetricsProxy_StreamsBody(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/metrics" || r.Method != http.MethodGet {
			http.Error(w, "unexpected", http.StatusBadRequest)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"anchors_created":42}`))
	}))
	defer fake.Close()

	s := newTestServer(fake.URL)

	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	rec := httptest.NewRecorder()
	s.handleMetricsProxy(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"anchors_created":42`) {
		t.Errorf("body = %q, want it to contain the upstream metrics", rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != metricsContentType {
		t.Errorf("Content-Type = %q, want the edge's own %q", ct, metricsContentType)
	}
}

func TestHandleMetricsProxy_ForwardsInternalAuth(t *testing.T) {
	var gotSecret string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Auth")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"errors":0}`))
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

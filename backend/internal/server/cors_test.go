package server

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

var testCORSOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

func TestCORS_AllowedOriginReflected(t *testing.T) {
	handler := corsMiddleware(testCORSOrigins)(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/api/cognition", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "http://localhost:3000" {
		t.Errorf("Access-Control-Allow-Origin = %q, want reflected origin", got)
	}
}

func TestCORS_DisallowedOriginNotReflected(t *testing.T) {
	handler := corsMiddleware(testCORSOrigins)(okHandler())

	req := httptest.NewRequest(http.MethodPost, "/api/cognition", nil)
	req.Header.Set("Origin", "https://evil.example.com")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("Access-Control-Allow-Origin = %q, want empty for disallowed origin", got)
	}
}

func TestCORS_NoOriginHeader(t *testing.T) {
	handler := corsMiddleware(testCORSOrigins)(okHandler())

	req := httptest.NewRequest(http.MethodGet, "/api/anchors", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Errorf("Access-Control-Allow-Origin = %q, want empty when no Origin", got)
	}
}

func TestCORS_PreflightShortCircuits(t *testing.T) {
	var nextCalled bool
	handler := corsMiddleware(testCORSOrigins)(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodOptions, "/api/cognition", nil)
	req.Header.Set("Origin", "http://localhost:3000")
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d, want 204", rec.Code)
	}
	if nextCalled {
		t.Error("preflight OPTIONS should short-circuit before next handler")
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "http://localhost:3000" {
		t.Errorf("preflight Access-Control-Allow-Origin = %q, want reflected origin", got)
	}
}

package server

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

func TestRequestIDMiddleware_GeneratesWhenAbsent(t *testing.T) {
	var seen string
	h := requestIDMiddleware(zerolog.Nop())(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = reqid.FromContext(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	got := rec.Header().Get(reqid.Header)
	if got == "" {
		t.Fatal("expected a generated X-Request-ID on the response")
	}
	if seen != got {
		t.Errorf("context id %q != response id %q", seen, got)
	}
}

func TestRequestIDMiddleware_PreservesInbound(t *testing.T) {
	var seen string
	h := requestIDMiddleware(zerolog.Nop())(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = reqid.FromContext(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	req.Header.Set(reqid.Header, "inbound-123")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if got := rec.Header().Get(reqid.Header); got != "inbound-123" {
		t.Errorf("response %s = %q, want inbound-123", reqid.Header, got)
	}
	if seen != "inbound-123" {
		t.Errorf("context id = %q, want inbound-123", seen)
	}
}

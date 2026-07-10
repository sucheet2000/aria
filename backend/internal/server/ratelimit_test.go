package server

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/auth"
)

func okHandler() http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
}

func doRequest(h http.Handler, owner, remoteAddr string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/api/cognition", nil)
	if remoteAddr != "" {
		req.RemoteAddr = remoteAddr
	}
	if owner != "" {
		req = req.WithContext(auth.WithOwner(req.Context(), owner))
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func TestRateLimiter_AllowsBurstThen429(t *testing.T) {
	// Per-caller burst of 2, effectively no refill; global generous.
	rl := newRateLimiter(0.001, 2, 1000, 1000)
	h := rl.Middleware(okHandler())

	for i := 1; i <= 2; i++ {
		if rec := doRequest(h, "userA", ""); rec.Code != http.StatusOK {
			t.Fatalf("request %d: status = %d, want 200", i, rec.Code)
		}
	}
	rec := doRequest(h, "userA", "")
	if rec.Code != http.StatusTooManyRequests {
		t.Fatalf("request 3: status = %d, want 429", rec.Code)
	}
}

func TestRateLimiter_PerCallerIsolation(t *testing.T) {
	rl := newRateLimiter(0.001, 1, 1000, 1000)
	h := rl.Middleware(okHandler())

	if rec := doRequest(h, "userA", ""); rec.Code != http.StatusOK {
		t.Fatalf("userA first: status = %d, want 200", rec.Code)
	}
	if rec := doRequest(h, "userA", ""); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("userA second: status = %d, want 429", rec.Code)
	}
	if rec := doRequest(h, "userB", ""); rec.Code != http.StatusOK {
		t.Fatalf("userB first: status = %d, want 200 (own bucket)", rec.Code)
	}
}

func TestRateLimiter_FallbackToIP(t *testing.T) {
	rl := newRateLimiter(0.001, 1, 1000, 1000)
	h := rl.Middleware(okHandler())

	if rec := doRequest(h, "", "1.2.3.4:5555"); rec.Code != http.StatusOK {
		t.Fatalf("ip first: status = %d, want 200", rec.Code)
	}
	// Same IP, different source port -> same bucket -> 429.
	if rec := doRequest(h, "", "1.2.3.4:6666"); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("same ip second: status = %d, want 429", rec.Code)
	}
	// Different IP -> own bucket -> 200.
	if rec := doRequest(h, "", "9.9.9.9:1000"); rec.Code != http.StatusOK {
		t.Fatalf("different ip: status = %d, want 200", rec.Code)
	}
}

func TestRateLimiter_GlobalCeiling(t *testing.T) {
	// Per-caller generous, global burst of 1: a second distinct caller is capped.
	rl := newRateLimiter(1000, 1000, 0.001, 1)
	h := rl.Middleware(okHandler())

	if rec := doRequest(h, "userA", ""); rec.Code != http.StatusOK {
		t.Fatalf("global first: status = %d, want 200", rec.Code)
	}
	if rec := doRequest(h, "userB", ""); rec.Code != http.StatusTooManyRequests {
		t.Fatalf("global ceiling: status = %d, want 429", rec.Code)
	}
}

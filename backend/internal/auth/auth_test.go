package auth

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

type fakeVerifier struct {
	owner  string
	err    error
	called bool
}

func (f *fakeVerifier) Verify(_ context.Context, _ string) (string, error) {
	f.called = true
	return f.owner, f.err
}

func TestOwnerFromContext_Empty(t *testing.T) {
	if owner := OwnerFromContext(context.Background()); owner != "" {
		t.Errorf("owner = %q, want empty", owner)
	}
}

func TestWithOwnerRoundTrip(t *testing.T) {
	ctx := WithOwner(context.Background(), "user_123")
	if owner := OwnerFromContext(ctx); owner != "user_123" {
		t.Errorf("owner = %q, want user_123", owner)
	}
}

func TestRequireAuth(t *testing.T) {
	tests := []struct {
		name       string
		enabled    bool
		verifier   *fakeVerifier
		authHeader string
		wantStatus int
		wantNext   bool
		wantVerify bool
		wantOwner  string
	}{
		{
			name:       "disabled passes through with no owner",
			enabled:    false,
			verifier:   &fakeVerifier{owner: "should-not-be-used"},
			authHeader: "",
			wantStatus: http.StatusOK,
			wantNext:   true,
			wantVerify: false,
			wantOwner:  "",
		},
		{
			name:       "enabled valid token sets owner",
			enabled:    true,
			verifier:   &fakeVerifier{owner: "user_abc"},
			authHeader: "Bearer good-token",
			wantStatus: http.StatusOK,
			wantNext:   true,
			wantVerify: true,
			wantOwner:  "user_abc",
		},
		{
			name:       "enabled missing header is 401",
			enabled:    true,
			verifier:   &fakeVerifier{owner: "user_abc"},
			authHeader: "",
			wantStatus: http.StatusUnauthorized,
			wantNext:   false,
			wantVerify: false,
		},
		{
			name:       "enabled malformed header is 401",
			enabled:    true,
			verifier:   &fakeVerifier{owner: "user_abc"},
			authHeader: "Token abc",
			wantStatus: http.StatusUnauthorized,
			wantNext:   false,
			wantVerify: false,
		},
		{
			name:       "enabled invalid token is 401",
			enabled:    true,
			verifier:   &fakeVerifier{err: errors.New("bad token")},
			authHeader: "Bearer bad-token",
			wantStatus: http.StatusUnauthorized,
			wantNext:   false,
			wantVerify: true,
		},
		{
			name:       "enabled empty owner is 401",
			enabled:    true,
			verifier:   &fakeVerifier{owner: ""},
			authHeader: "Bearer weird-token",
			wantStatus: http.StatusUnauthorized,
			wantNext:   false,
			wantVerify: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var nextCalled bool
			var gotOwner string
			next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				nextCalled = true
				gotOwner = OwnerFromContext(r.Context())
				w.WriteHeader(http.StatusOK)
			})

			handler := RequireAuth(tt.verifier, tt.enabled)(next)

			req := httptest.NewRequest(http.MethodGet, "/api/x", nil)
			if tt.authHeader != "" {
				req.Header.Set("Authorization", tt.authHeader)
			}
			rec := httptest.NewRecorder()
			handler.ServeHTTP(rec, req)

			if rec.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d", rec.Code, tt.wantStatus)
			}
			if nextCalled != tt.wantNext {
				t.Fatalf("next called = %v, want %v", nextCalled, tt.wantNext)
			}
			if tt.verifier.called != tt.wantVerify {
				t.Errorf("verifier called = %v, want %v", tt.verifier.called, tt.wantVerify)
			}
			if tt.wantNext && gotOwner != tt.wantOwner {
				t.Errorf("owner = %q, want %q", gotOwner, tt.wantOwner)
			}
		})
	}
}

func TestRequireAuth_NilVerifierWhenDisabled(t *testing.T) {
	var nextCalled bool
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		nextCalled = true
		w.WriteHeader(http.StatusOK)
	})

	handler := RequireAuth(nil, false)(next)

	req := httptest.NewRequest(http.MethodGet, "/api/x", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if !nextCalled {
		t.Fatal("expected next handler to be called when disabled")
	}
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
}

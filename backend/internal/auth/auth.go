// Package auth provides the Clerk-JWT authentication boundary for the ARIA
// backend. Go is the single point where the browser's session token is
// verified; downstream Python services trust the X-Aria-Owner header Go sets.
package auth

import (
	"context"
	"net/http"
	"strings"
)

// OwnerHeader is the header Go sets on outgoing requests to the internal Python
// service to identify the authenticated Clerk user.
const OwnerHeader = "X-Aria-Owner"

// Verifier validates a session token and returns the owner (Clerk user id).
type Verifier interface {
	Verify(ctx context.Context, token string) (owner string, err error)
}

type ownerContextKey struct{}

// WithOwner returns a copy of ctx carrying the given owner.
func WithOwner(ctx context.Context, owner string) context.Context {
	return context.WithValue(ctx, ownerContextKey{}, owner)
}

// OwnerFromContext returns the authenticated owner stored in ctx, or "" if none.
func OwnerFromContext(ctx context.Context) string {
	owner, _ := ctx.Value(ownerContextKey{}).(string)
	return owner
}

// RequireAuth is a chi middleware that enforces a valid Clerk session token.
//
// When enabled is false (no Clerk secret key configured), it is a pass-through
// no-op that sets no owner, so local development without Clerk still works.
// When enabled is true, it reads the Authorization: Bearer header, verifies the
// token with v, stores the resulting owner in the request context, and responds
// 401 on a missing, malformed, or invalid token.
func RequireAuth(v Verifier, enabled bool) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !enabled {
				next.ServeHTTP(w, r)
				return
			}

			token := bearerToken(r)
			if token == "" {
				writeUnauthorized(w)
				return
			}

			owner, err := v.Verify(r.Context(), token)
			if err != nil || owner == "" {
				writeUnauthorized(w)
				return
			}

			next.ServeHTTP(w, r.WithContext(WithOwner(r.Context(), owner)))
		})
	}
}

func bearerToken(r *http.Request) string {
	const prefix = "Bearer "
	header := r.Header.Get("Authorization")
	if len(header) <= len(prefix) || !strings.EqualFold(header[:len(prefix)], prefix) {
		return ""
	}
	return strings.TrimSpace(header[len(prefix):])
}

func writeUnauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	w.Write([]byte(`{"error":"unauthorized"}`)) //nolint:errcheck
}

package server

import (
	"net/http"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// requestIDMiddleware reads or generates an X-Request-ID for each inbound
// request, echoes it on the response, stores it in the request context, and
// attaches a per-request zerolog logger tagged with request_id so downstream
// handlers log with the correlation id. The id is forwarded to Python on
// internal calls via reqid.SetHeader.
func requestIDMiddleware(base zerolog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			id := r.Header.Get(reqid.Header)
			if id == "" {
				id = reqid.New()
			}
			w.Header().Set(reqid.Header, id)

			ctx := reqid.WithID(r.Context(), id)
			reqLog := base.With().Str("request_id", id).Logger()
			ctx = reqLog.WithContext(ctx)

			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

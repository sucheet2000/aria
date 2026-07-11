// Package reqid provides request-correlation IDs shared across the ARIA Go edge
// and forwarded to the internal Python service, so a single request can be
// traced end-to-end in the logs of both services.
package reqid

import (
	"context"
	"crypto/rand"
	"fmt"
	"net/http"
)

// Header is the HTTP header carrying the request-correlation ID across the edge
// and on internal calls to the Python service.
const Header = "X-Request-ID"

type ctxKey struct{}

// New returns a random RFC-4122 version-4 UUID string generated with crypto/rand.
func New() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40 // version 4
	b[8] = (b[8] & 0x3f) | 0x80 // variant 10
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

// WithID returns a copy of ctx carrying the given request ID.
func WithID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKey{}, id)
}

// FromContext returns the request ID stored in ctx, or "" if none.
func FromContext(ctx context.Context) string {
	id, _ := ctx.Value(ctxKey{}).(string)
	return id
}

// SetHeader copies the request ID from ctx onto req's X-Request-ID header when
// present. It is a no-op when ctx carries no request ID.
func SetHeader(req *http.Request, ctx context.Context) {
	if id := FromContext(ctx); id != "" {
		req.Header.Set(Header, id)
	}
}

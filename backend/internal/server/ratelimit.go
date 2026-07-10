package server

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"sync"
	"time"

	"github.com/sucheet2000/aria/backend/internal/auth"
	"golang.org/x/time/rate"
)

const (
	// visitorTTL is how long an idle per-caller bucket is retained before sweep.
	visitorTTL = 10 * time.Minute
	// visitorSweepPeriod is how often the idle-bucket sweep runs.
	visitorSweepPeriod = time.Minute
)

type visitor struct {
	limiter  *rate.Limiter
	lastSeen time.Time
}

// rateLimiter enforces a per-caller token bucket plus a global ceiling on the
// paid endpoints. Callers are keyed by the authenticated owner
// (auth.OwnerFromContext), falling back to the client IP when no owner is set.
type rateLimiter struct {
	perRate  rate.Limit
	perBurst int
	global   *rate.Limiter

	mu       sync.Mutex
	visitors map[string]*visitor
}

// newRateLimiter builds a rateLimiter from per-caller rate/burst and global
// rate/burst settings (rates are tokens per second).
func newRateLimiter(perRPS float64, perBurst int, globalRPS float64, globalBurst int) *rateLimiter {
	return &rateLimiter{
		perRate:  rate.Limit(perRPS),
		perBurst: perBurst,
		global:   rate.NewLimiter(rate.Limit(globalRPS), globalBurst),
		visitors: make(map[string]*visitor),
	}
}

// start launches the background sweep that evicts idle per-caller buckets.
// It returns when ctx is cancelled.
func (rl *rateLimiter) start(ctx context.Context) {
	go rl.sweepLoop(ctx)
}

func (rl *rateLimiter) sweepLoop(ctx context.Context) {
	ticker := time.NewTicker(visitorSweepPeriod)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			rl.sweep(time.Now())
		}
	}
}

func (rl *rateLimiter) sweep(now time.Time) {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	for key, v := range rl.visitors {
		if now.Sub(v.lastSeen) > visitorTTL {
			delete(rl.visitors, key)
		}
	}
}

func (rl *rateLimiter) limiterFor(key string) *rate.Limiter {
	rl.mu.Lock()
	defer rl.mu.Unlock()
	v, ok := rl.visitors[key]
	if !ok {
		v = &visitor{limiter: rate.NewLimiter(rl.perRate, rl.perBurst)}
		rl.visitors[key] = v
	}
	v.lastSeen = time.Now()
	return v.limiter
}

// Middleware is a chi-compatible middleware that rejects requests exceeding the
// per-caller bucket or the global ceiling with 429. The per-caller bucket is
// consumed first; the global token is only drawn when the per-caller check passes.
func (rl *rateLimiter) Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !rl.limiterFor(callerKey(r)).Allow() || !rl.global.Allow() {
			writeRateLimited(w)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// callerKey identifies the caller: the authenticated owner when present,
// otherwise the client IP. The two are namespaced so an IP cannot collide
// with a Clerk user id.
func callerKey(r *http.Request) string {
	if owner := auth.OwnerFromContext(r.Context()); owner != "" {
		return "owner:" + owner
	}
	return "ip:" + clientIP(r)
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

func writeRateLimited(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusTooManyRequests)
	json.NewEncoder(w).Encode(map[string]string{"error": "rate limit exceeded"}) //nolint:errcheck
}

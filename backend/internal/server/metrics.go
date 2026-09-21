package server

import (
	"crypto/subtle"
	"io"
	"mime"
	"net/http"
	"strings"

	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// metricsContentType is what this endpoint actually serves. The Python handler
// returns MetricsCollector().snapshot(), a plain dict rendered by FastAPI's
// default JSONResponse — so this is JSON, not Prometheus text exposition, and
// claiming otherwise would be a lie a scraper would discover the hard way.
//
// It is set explicitly rather than copied from upstream. Relaying the upstream
// type let a non-metrics response — an HTML error page, an SVG — be served as
// document content from ARIA's own origin, which is where Clerk session
// material lives.
const metricsContentType = "application/json; charset=utf-8"

// maxMetricsBodyBytes caps what the edge will relay. The sibling proxy has had
// such a cap all along; this handler streamed an unbounded io.Copy, so a
// misbehaving or compromised upstream could push arbitrary volume through the
// edge to any authorised scraper.
const maxMetricsBodyBytes int64 = 4 << 20

// handleMetricsProxy exposes GET /metrics through the edge, which OBS-3
// requires (reachable publicly, not loopback-only). OBS-3 says nothing about
// authentication, and the data here — operational counters and Claude token
// spend — is not public information, so the route carries its own scrape
// credential.
func (s *Server) handleMetricsProxy(w http.ResponseWriter, r *http.Request) {
	if !s.metricsAuthorized(r) {
		writeMetricsError(w, http.StatusUnauthorized, `{"error":"unauthorized"}`)
		return
	}

	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, s.pythonURL+"/metrics", nil)
	if err != nil {
		writeMetricsError(w, http.StatusInternalServerError, `{"error":"internal error"}`)
		return
	}
	auth.SetInternalAuth(req, s.cfg.InternalAuthSecret)
	reqid.SetHeader(req, r.Context())

	resp, err := s.httpClient.Do(req)
	if err != nil {
		// S2: the cause is logged, never echoed — the error text carries the
		// internal upstream URL.
		log.Error().Err(err).Msg("metrics upstream unreachable")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}
	defer resp.Body.Close()

	// Anything other than a clean 200 is not metrics. Relaying the upstream
	// status verbatim turned a Python 403 or a redirect into that same answer
	// from the edge, which tells an outside caller about our internals and, for
	// a 3xx, hands them a redirect we did not author.
	if resp.StatusCode != http.StatusOK {
		log.Error().Int("upstream_status", resp.StatusCode).Msg("metrics upstream returned a non-200")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}

	// And it must actually be JSON. Safe headers stop a browser RENDERING an
	// HTML body, but they do not stop the edge handing that body to the caller
	// in the first place; a 200 carrying markup is not metrics whatever we
	// label it, so it is refused rather than relayed.
	if !isJSONContentType(resp.Header.Get("Content-Type")) {
		log.Error().Str("upstream_content_type", resp.Header.Get("Content-Type")).
			Msg("metrics upstream did not return JSON")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}

	w.Header().Set("Content-Type", metricsContentType)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	// Operational counters are a point-in-time reading; a cached copy is both
	// wrong and needlessly retained by any intermediary.
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)

	if _, err := io.Copy(w, io.LimitReader(resp.Body, maxMetricsBodyBytes)); err != nil {
		log.Error().Err(err).Msg("metrics stream interrupted")
	}
}

// isJSONContentType reports whether an upstream media type is JSON. Parameters
// (charset) are allowed, case is not significant (RFC 9110), and an absent or
// unparseable type is not a promise of anything.
func isJSONContentType(ct string) bool {
	media, _, err := mime.ParseMediaType(ct)
	if err != nil {
		return false
	}
	return media == "application/json"
}

// metricsAuthorized reports whether the request carries the scrape credential.
//
// When no token is configured the endpoint stays open: that is the documented
// local-development posture, and Start refuses to boot in that state on a
// non-loopback bind, so it cannot silently become the production posture.
func (s *Server) metricsAuthorized(r *http.Request) bool {
	want := s.cfg.MetricsToken
	if want == "" {
		return true
	}
	got := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if got == r.Header.Get("Authorization") {
		// No "Bearer " prefix at all.
		return false
	}
	// Constant-time: a byte-by-byte comparison would let a caller discover the
	// token one character at a time from response timing.
	return subtle.ConstantTimeCompare([]byte(got), []byte(want)) == 1
}

// writeMetricsError answers with a fixed body. Every failure looks the same
// from outside: no upstream status, no upstream body, no internal URL, and
// nothing that says which part of a credential was wrong.
func writeMetricsError(w http.ResponseWriter, status int, body string) {
	w.Header().Set("Content-Type", metricsContentType)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	w.Write([]byte(body)) //nolint:errcheck
}

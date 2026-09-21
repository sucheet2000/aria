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

	// Refuse redirects. Go's default policy follows up to ten and strips
	// Authorization across hosts, but NOT a custom header — so a 3xx from the
	// upstream would send INTERNAL_AUTH_SECRET to whatever host it named and
	// bring that host's body back as our response. The status check below
	// cannot help: by the time a response exists the request has been made.
	//
	// ErrUseLastResponse hands the 3xx itself back instead of following it, so
	// the check below sees it and answers 502. The client is copied rather than
	// mutated because it is shared with the other proxies.
	noRedirect := *s.httpClient
	noRedirect.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}

	resp, err := noRedirect.Do(req)
	if err != nil {
		// S2: the cause is logged, never echoed — the error text carries the
		// internal upstream URL.
		log.Error().Err(err).Msg("metrics upstream unreachable")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}
	defer resp.Body.Close()

	// Anything other than a clean 200 is not metrics. Relaying the upstream
	// status verbatim told an outside caller about our internals — a Python 403
	// surfaced as a 403 from the edge. A 3xx reaches here only because the
	// redirect policy above declined to follow it.
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

	// Read one byte past the cap so an overflow is detectable. Truncating at
	// the cap produced a 200 labelled JSON carrying a document cut in half,
	// with nothing to tell the scraper it was incomplete — a silent wrong
	// answer is worse than a loud failure.
	counted := &countingReader{r: io.LimitReader(resp.Body, maxMetricsBodyBytes+1)}
	body, err := io.ReadAll(counted)
	lastMetricsBytesRead = counted.n
	if err != nil {
		log.Error().Err(err).Msg("metrics stream interrupted")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}
	if int64(len(body)) > maxMetricsBodyBytes {
		log.Error().Int("bytes", len(body)).Msg("metrics upstream exceeded the response cap")
		writeMetricsError(w, http.StatusBadGateway, `{"error":"metrics unavailable"}`)
		return
	}

	w.Header().Set("Content-Type", metricsContentType)
	w.Header().Set("X-Content-Type-Options", "nosniff")
	// Operational counters are a point-in-time reading; a cached copy is both
	// wrong and needlessly retained by any intermediary.
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	w.Write(body) //nolint:errcheck
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

// lastMetricsBytesRead is how many bytes the most recent scrape pulled from
// the upstream. Test-only window: the cap is a promise about what we read, and
// the response alone cannot show it was kept.
var lastMetricsBytesRead int64

// countingReader records how many bytes were actually pulled from the
// upstream. Without it the cap was only ever a check on a buffer we had
// already filled: reading the whole body and then refusing it still passes a
// test that asserts the refusal, while a 10 GB upstream is held in memory
// first. What matters is that we stop reading.
type countingReader struct {
	r io.Reader
	n int64
}

func (c *countingReader) Read(p []byte) (int, error) {
	n, err := c.r.Read(p)
	c.n += int64(n)
	return n, err
}

// metricsAuthorized reports whether the request carries the scrape credential.
//
// When no token is configured the endpoint stays open: that is the documented
// local-development posture, and Start refuses to boot in that state on a
// non-loopback bind, so it cannot silently become the production posture.
func (s *Server) metricsAuthorized(r *http.Request) bool {
	// A token that is only whitespace is not a credential; treat it as unset so
	// it cannot be "presented" and matched against itself. The COMPARISON uses
	// the raw value: trimming it too would mean METRICS_TOKEN=" abc " silently
	// accepts only "abc", and since the denial deliberately gives no oracle the
	// operator would debug an identical 401 with no signal at all.
	want := s.cfg.MetricsToken
	if strings.TrimSpace(want) == "" {
		return true
	}

	// Exactly one Authorization header. Two is malformed (RFC 7235), and Go's
	// Get returns the first — so "valid, garbage" was accepted while
	// "garbage, valid" was refused, which desyncs us from any fronting proxy
	// that picks the other one.
	headers := r.Header.Values("Authorization")
	if len(headers) != 1 {
		return false
	}
	got := strings.TrimPrefix(headers[0], "Bearer ")
	if got == headers[0] {
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

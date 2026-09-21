package server

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// M1 — /metrics was registered outside the only group carrying auth, CORS and
// rate limiting, and the proxy relayed the upstream's status, Content-Type and
// body verbatim with no size cap and no nosniff. Operational data and token
// spend were readable by anyone who could reach the port, and a non-metrics
// upstream response could be served as document content on ARIA's own origin.

const testMetricsToken = "metrics-token-SECRET-VALUE-1234567890"

func newMetricsServer(pythonURL, token string) *Server {
	cfg := &config.Config{Port: 0, MetricsToken: token}
	s := New(cfg, NewHub(), memory.New(5))
	s.pythonURL = pythonURL
	s.httpClient = &http.Client{Timeout: 5 * time.Second}
	return s
}

// upstream returns a fake Python /metrics speaking whatever the test needs.
func upstream(t *testing.T, status int, contentType, body string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		if contentType != "" {
			w.Header().Set("Content-Type", contentType)
		} else {
			w.Header()["Content-Type"] = nil
		}
		w.WriteHeader(status)
		w.Write([]byte(body)) //nolint:errcheck
	}))
	t.Cleanup(srv.Close)
	return srv
}

func scrape(s *Server, authHeader string) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodGet, "/metrics", nil)
	if authHeader != "" {
		req.Header.Set("Authorization", authHeader)
	}
	rec := httptest.NewRecorder()
	s.handleMetricsProxy(rec, req)
	return rec
}

// ── AUTH ────────────────────────────────────────────────────────────────────

func TestMetrics_ValidCredentialSucceeds(t *testing.T) {
	up := upstream(t, 200, "application/json", `{"errors":0}`)
	rec := scrape(newMetricsServer(up.URL, testMetricsToken), "Bearer "+testMetricsToken)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 for a legitimate scrape; body %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"errors":0`) {
		t.Fatalf("body = %q, want the upstream metrics", rec.Body.String())
	}
}

func TestMetrics_RejectsWithoutCredential(t *testing.T) {
	up := upstream(t, 200, "application/json", `{"token_cost":{"claude":{"uncached":99}}}`)
	rec := scrape(newMetricsServer(up.URL, testMetricsToken), "")

	if rec.Code == http.StatusOK {
		t.Fatalf("an unauthenticated caller read the metrics: %s", rec.Body.String())
	}
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", rec.Code)
	}
	if strings.Contains(rec.Body.String(), "token_cost") {
		t.Fatal("operational data leaked in the denial body")
	}
}

func TestMetrics_RejectsBadCredentials(t *testing.T) {
	cases := []struct {
		name   string
		header string
	}{
		{"wrong token", "Bearer completely-wrong-token"},
		{"prefix of the real token", "Bearer " + testMetricsToken[:10]},
		{"real token plus a suffix", "Bearer " + testMetricsToken + "x"},
		{"malformed - no scheme", testMetricsToken},
		{"malformed - wrong scheme", "Basic " + testMetricsToken},
		{"empty bearer", "Bearer "},
		{"bearer with only spaces", "Bearer    "},
		{"leading whitespace in token", "Bearer  " + testMetricsToken},
		{"trailing whitespace in token", "Bearer " + testMetricsToken + " "},
		{"enormous header", "Bearer " + strings.Repeat("A", 1<<20)},
		{"null byte", "Bearer " + testMetricsToken + "\x00"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			up := upstream(t, 200, "application/json", `{"errors":0}`)
			rec := scrape(newMetricsServer(up.URL, testMetricsToken), tc.header)

			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("status = %d for %q, want 401", rec.Code, tc.name)
			}
			// The denial must not say which part was wrong.
			if body := rec.Body.String(); strings.Contains(body, "prefix") ||
				strings.Contains(body, "expected") || strings.Contains(body, testMetricsToken) {
				t.Fatalf("denial body is an oracle: %q", body)
			}
		})
	}
}

// A user's Clerk session is not an infrastructure credential.
func TestMetrics_ClerkStyleBearerIsNotAScrapeCredential(t *testing.T) {
	up := upstream(t, 200, "application/json", `{"errors":0}`)
	rec := scrape(newMetricsServer(up.URL, testMetricsToken),
		"Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.sig")

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401 — a user token must not grant metrics access", rec.Code)
	}
}

func TestMetrics_CredentialNeverAppearsInLogsOrResponse(t *testing.T) {
	var logged bytes.Buffer
	prev := log.Logger
	log.Logger = zerolog.New(&logged)
	defer func() { log.Logger = prev }()

	up := upstream(t, 200, "application/json", `{"errors":0}`)
	s := newMetricsServer(up.URL, testMetricsToken)

	for _, h := range []string{"", "Bearer wrong-" + testMetricsToken, "Bearer " + testMetricsToken} {
		rec := scrape(s, h)
		if strings.Contains(rec.Body.String(), testMetricsToken) {
			t.Fatal("the metrics token was echoed in a response body")
		}
	}
	if strings.Contains(logged.String(), testMetricsToken) {
		t.Fatalf("the metrics token reached the log: %s", logged.String())
	}
}

// ── RESPONSE SAFETY ─────────────────────────────────────────────────────────

func TestMetrics_UpstreamContentTypeNeverBecomesActiveContent(t *testing.T) {
	hostile := []struct {
		name        string
		contentType string
		body        string
	}{
		{"html", "text/html", "<html><body>hi</body></html>"},
		{"html with script", "text/html; charset=utf-8", `<script>alert(document.domain)</script>`},
		{"json", "application/json", `{"a":1}`},
		{"svg", "image/svg+xml", `<svg xmlns="http://www.w3.org/2000/svg"><script>1</script></svg>`},
		{"mixed case html", "TeXt/HtMl", "<b>x</b>"},
		{"malformed", "not a media type at all", "x"},
		{"absent", "", "<html><script>alert(1)</script></html>"},
	}
	for _, tc := range hostile {
		t.Run(tc.name, func(t *testing.T) {
			up := upstream(t, 200, tc.contentType, tc.body)
			rec := scrape(newMetricsServer(up.URL, testMetricsToken), "Bearer "+testMetricsToken)

			got := rec.Header().Get("Content-Type")
			if strings.Contains(strings.ToLower(got), "html") ||
				strings.Contains(strings.ToLower(got), "svg") {
				t.Fatalf("served %q from our own origin", got)
			}
			if got != metricsContentType {
				t.Fatalf("Content-Type = %q, want the explicit %q", got, metricsContentType)
			}
			if rec.Header().Get("X-Content-Type-Options") != "nosniff" {
				t.Fatal("nosniff missing — the browser may sniff the body")
			}
		})
	}
}

func TestMetrics_SuccessCarriesTheSafeHeaders(t *testing.T) {
	up := upstream(t, 200, "application/json", `{"errors":0}`)
	rec := scrape(newMetricsServer(up.URL, testMetricsToken), "Bearer "+testMetricsToken)

	if got := rec.Header().Get("Content-Type"); got != metricsContentType {
		t.Fatalf("Content-Type = %q, want %q", got, metricsContentType)
	}
	if got := rec.Header().Get("X-Content-Type-Options"); got != "nosniff" {
		t.Fatalf("X-Content-Type-Options = %q, want nosniff", got)
	}
	if got := rec.Header().Get("Cache-Control"); got != "no-store" {
		t.Fatalf("Cache-Control = %q, want no-store", got)
	}
}

// ── STATUS MAPPING AND BODY CONFINEMENT ─────────────────────────────────────

func TestMetrics_UpstreamFailureIsNormalisedAndNeverLeaksItsBody(t *testing.T) {
	const secret = "UPSTREAM-DIAGNOSTIC-SHOULD-NOT-APPEAR"
	for _, status := range []int{301, 302, 400, 401, 403, 404, 418, 500, 502, 503} {
		t.Run(fmt.Sprintf("upstream %d", status), func(t *testing.T) {
			up := upstream(t, status, "text/html", "<html>"+secret+"</html>")
			rec := scrape(newMetricsServer(up.URL, testMetricsToken), "Bearer "+testMetricsToken)

			if rec.Code == http.StatusOK {
				t.Fatalf("upstream %d was relayed as a successful scrape", status)
			}
			if rec.Code != http.StatusBadGateway {
				t.Fatalf("status = %d, want 502 for any unusable upstream response", rec.Code)
			}
			if strings.Contains(rec.Body.String(), secret) {
				t.Fatalf("upstream body leaked: %q", rec.Body.String())
			}
			if strings.Contains(rec.Body.String(), up.URL) {
				t.Fatal("internal upstream URL leaked to the caller")
			}
		})
	}
}

func TestMetrics_UpstreamUnreachableIsSafe(t *testing.T) {
	dead := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := dead.URL
	dead.Close() // nothing is listening now

	rec := scrape(newMetricsServer(url, testMetricsToken), "Bearer "+testMetricsToken)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want 502 when Python is down", rec.Code)
	}
	if strings.Contains(rec.Body.String(), url) {
		t.Fatal("internal URL leaked")
	}
	if rec.Header().Get("X-Content-Type-Options") != "nosniff" {
		t.Fatal("nosniff missing on the failure path")
	}
}

func TestMetrics_OversizedUpstreamBodyIsBounded(t *testing.T) {
	huge := strings.Repeat("x", int(maxMetricsBodyBytes)+4096)
	up := upstream(t, 200, "application/json", huge)
	rec := scrape(newMetricsServer(up.URL, testMetricsToken), "Bearer "+testMetricsToken)

	if int64(rec.Body.Len()) > maxMetricsBodyBytes {
		t.Fatalf("relayed %d bytes, cap is %d — an upstream can exhaust the edge",
			rec.Body.Len(), maxMetricsBodyBytes)
	}
}

// ── OVER THE WIRE ───────────────────────────────────────────────────────────

// A recorder cannot show what a browser receives. This drives the real router
// so the registration, the middleware chain and the headers are all exercised.
func TestMetrics_OverTheWire(t *testing.T) {
	up := upstream(t, 200, "text/html", "<html><script>alert(1)</script></html>")
	s := newMetricsServer(up.URL, testMetricsToken)
	s.routes(context.Background(), nil, false)

	edge := httptest.NewServer(s.router)
	defer edge.Close()

	t.Run("no credential", func(t *testing.T) {
		resp, err := http.Get(edge.URL + "/metrics")
		if err != nil {
			t.Fatalf("get: %v", err)
		}
		defer resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Fatalf("status = %d over the wire, want 401", resp.StatusCode)
		}
	})

	t.Run("with credential, hostile upstream", func(t *testing.T) {
		req, _ := http.NewRequest(http.MethodGet, edge.URL+"/metrics", nil)
		req.Header.Set("Authorization", "Bearer "+testMetricsToken)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatalf("get: %v", err)
		}
		defer resp.Body.Close()
		body, _ := io.ReadAll(resp.Body)

		if ct := resp.Header.Get("Content-Type"); strings.Contains(strings.ToLower(ct), "html") {
			t.Fatalf("the wire carried %q — a browser would render this on our origin", ct)
		}
		if resp.Header.Get("X-Content-Type-Options") != "nosniff" {
			t.Fatal("nosniff absent on the wire")
		}
		if strings.Contains(string(body), "<script>") {
			t.Fatalf("upstream HTML reached the client: %q", string(body))
		}
	})
}

// /health must be unchanged: Railway probes it.
func TestMetrics_HealthRemainsOpen(t *testing.T) {
	s := newMetricsServer("http://127.0.0.1:1", testMetricsToken)
	s.routes(context.Background(), nil, false)
	edge := httptest.NewServer(s.router)
	defer edge.Close()

	resp, err := http.Get(edge.URL + "/health")
	if err != nil {
		t.Fatalf("get: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("/health status = %d without a credential, want 200", resp.StatusCode)
	}
}

// ── ABUSE / RESOURCE BEHAVIOUR (Phase 9) ────────────────────────────────────

// The cost question the credential actually answers: a caller without one is
// refused at the edge and never reaches Python, so an unauthenticated flood
// cannot be amplified into upstream work. Measured at 0 hops over 2000
// rejected requests; this pins the property rather than the number.
func TestMetrics_RejectedScrapesNeverReachUpstream(t *testing.T) {
	var hops int
	var mu sync.Mutex
	up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		mu.Lock()
		hops++
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"errors":0}`)) //nolint:errcheck
	}))
	defer up.Close()

	s := newMetricsServer(up.URL, testMetricsToken)
	for i := 0; i < 200; i++ {
		scrape(s, "")
		scrape(s, "Bearer wrong")
	}

	mu.Lock()
	defer mu.Unlock()
	if hops != 0 {
		t.Fatalf("%d unauthorised requests reached Python; the credential must stop them at the edge", hops)
	}
}

// Repeated authenticated scraping must not accumulate goroutines. Monitoring
// is by definition a repeating caller, so a per-scrape leak would be unbounded
// over the life of the process.
func TestMetrics_RepeatedScrapingDoesNotLeakGoroutines(t *testing.T) {
	up := upstream(t, 200, "application/json", `{"errors":0}`)
	s := newMetricsServer(up.URL, testMetricsToken)

	// Warm up so one-time internals are not counted as growth.
	for i := 0; i < 50; i++ {
		scrape(s, "Bearer "+testMetricsToken)
	}
	runtime.GC()
	before := runtime.NumGoroutine()

	var wg sync.WaitGroup
	for w := 0; w < 16; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for i := 0; i < 100; i++ {
				scrape(s, "Bearer "+testMetricsToken)
			}
		}()
	}
	wg.Wait()
	time.Sleep(200 * time.Millisecond)
	runtime.GC()

	if after := runtime.NumGoroutine(); after > before+5 {
		t.Fatalf("goroutines %d -> %d after 1600 scrapes", before, after)
	}
}

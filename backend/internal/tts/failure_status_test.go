package tts

import (
	"bytes"
	"io"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"testing"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Closure 2 — when no speech can be produced, the endpoint must not advertise a
// successful audio response.
//
// The handler set Content-Type: audio/mpeg and then called Stream. Go commits
// the status on the first body byte, so by the time Stream failed the response
// was already a 200 carrying an empty audio body. The caller could not tell a
// silent reply from a broken one, and the log was the only place the failure
// appeared.

func newFailingUpstream(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func newWorkingUpstream(t *testing.T, body string) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte(body)) //nolint:errcheck
	}))
	t.Cleanup(srv.Close)
	return srv
}

func post(t *testing.T, h http.Handler, body string) *httptest.ResponseRecorder {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/api/tts", strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

// 1 — the ordinary path is untouched.
func TestTTSHandler_UpstreamSuccessReturnsAudio(t *testing.T) {
	c := New("", "")
	c.SetPythonURL(newWorkingUpstream(t, "mp3-bytes").URL)
	rec := post(t, NewHandler(c), `{"text":"hello"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Body.String(); got != "mp3-bytes" {
		t.Fatalf("body = %q", got)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "audio/mpeg" {
		t.Fatalf("content-type = %q", ct)
	}
}

// 3 and 4 — upstream fails, no local synthesizer: a non-2xx, and no empty
// audio body pretending to be speech.
func TestTTSHandler_NoSpeechPossibleReturnsAnError(t *testing.T) {
	withoutLocalFallback(t)
	c := New("", "")
	c.SetPythonURL(newFailingUpstream(t).URL)

	rec := post(t, NewHandler(c), `{"text":"hello"}`)

	if rec.Code == http.StatusOK {
		t.Fatalf("status = 200 with no audio; the client cannot tell silence from failure")
	}
	if rec.Code < 500 || rec.Code > 599 {
		t.Fatalf("status = %d, want a 5xx", rec.Code)
	}
	if ct := rec.Header().Get("Content-Type"); strings.HasPrefix(ct, "audio/") {
		t.Fatalf("failure advertised itself as %q", ct)
	}
}

// 5 — the audio headers must not be committed before a stream is known to exist.
func TestTTSHandler_DoesNotCommitAudioHeadersBeforeItHasAStream(t *testing.T) {
	withoutLocalFallback(t)
	c := New("", "")
	c.SetPythonURL(newFailingUpstream(t).URL)

	rec := post(t, NewHandler(c), `{"text":"hello"}`)

	if rec.Header().Get("Transfer-Encoding") != "" {
		t.Fatal("chunked audio framing was announced for a response that carries none")
	}
	if rec.Body.Len() == 0 && rec.Code == http.StatusOK {
		t.Fatal("empty 200")
	}
}

// 8 — the provider's own response body must never be echoed to the caller.
func TestTTSHandler_DoesNotLeakTheUpstreamBody(t *testing.T) {
	withoutLocalFallback(t)
	secret := "upstream-diagnostic-SHOULD-NOT-APPEAR"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(secret)) //nolint:errcheck
	}))
	defer srv.Close()

	c := New("", "")
	c.SetPythonURL(srv.URL)
	rec := post(t, NewHandler(c), `{"text":"hello"}`)

	if strings.Contains(rec.Body.String(), secret) {
		t.Fatal("the upstream response body reached the client")
	}
}

// A short but valid stream is still a success: the fix must not treat "small"
// as "failed".
func TestTTSHandler_ShortAudioIsStillASuccess(t *testing.T) {
	c := New("", "")
	c.SetPythonURL(newWorkingUpstream(t, "x").URL)
	rec := post(t, NewHandler(c), `{"text":"hi"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 for a short but real stream", rec.Code)
	}
	if rec.Body.String() != "x" {
		t.Fatalf("body = %q", rec.Body.String())
	}
}

// 2 — upstream fails but this machine can synthesize locally: the caller still
// gets audio and a 200. Uses the OS `say` binary, which is local and free; on a
// platform without it there is nothing to assert, and test 3 above already
// covers that case.
func TestTTSHandler_UpstreamErrorWithLocalFallbackStillReturnsAudio(t *testing.T) {
	if !localFallbackAvailable() {
		t.Skipf("no local synthesizer on %s", runtime.GOOS)
	}
	c := New("", "")
	c.SetPythonURL(newFailingUpstream(t).URL)

	rec := post(t, NewHandler(c), `{"text":"hello"}`)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200 — the fallback can speak", rec.Code)
	}
	if rec.Body.Len() < 100 {
		t.Fatalf("body = %d bytes; the browser treats anything under 100 as unusable", rec.Body.Len())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "audio/mpeg" {
		t.Fatalf("content-type = %q", ct)
	}
}

// 8 — the provider's body must not reach the log either. It can quote the text
// ARIA is speaking, which is user content (S2).
func TestTTSHandler_DoesNotLogTheUpstreamBody(t *testing.T) {
	withoutLocalFallback(t)
	secret := "upstream-diagnostic-SHOULD-NOT-APPEAR"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte(secret)) //nolint:errcheck
	}))
	defer srv.Close()

	var logged bytes.Buffer
	prev := log.Logger
	log.Logger = zerolog.New(&logged)
	defer func() { log.Logger = prev }()

	c := New("", "")
	c.SetPythonURL(srv.URL)
	post(t, NewHandler(c), `{"text":"hello"}`)

	if strings.Contains(logged.String(), secret) {
		t.Fatalf("the upstream body was written to the log: %s", logged.String())
	}
	if !strings.Contains(logged.String(), "tts stream failed") {
		t.Fatalf("the failure was not logged at all: %s", logged.String())
	}
}

// 3 again, over a real socket. httptest.ResponseRecorder honours a late
// WriteHeader that a real connection would have already sent, so a recorder
// alone cannot see a status that was committed too early. This runs the handler
// behind a real server and reads the status the way the browser does.
func TestTTSHandler_TheClientSeesTheFailureStatusOnTheWire(t *testing.T) {
	withoutLocalFallback(t)
	c := New("", "")
	c.SetPythonURL(newFailingUpstream(t).URL)

	srv := httptest.NewServer(NewHandler(c))
	defer srv.Close()

	resp, err := http.Post(srv.URL, "application/json", strings.NewReader(`{"text":"hello"}`))
	if err != nil {
		t.Fatalf("post: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	if resp.StatusCode == http.StatusOK {
		t.Fatalf("the wire carried 200 with %d bytes of body; the browser cannot tell this from silence", len(body))
	}
	if resp.StatusCode/100 != 5 {
		t.Fatalf("status = %d, want a 5xx", resp.StatusCode)
	}
	if strings.HasPrefix(resp.Header.Get("Content-Type"), "audio/") {
		t.Fatalf("failure advertised itself as %q", resp.Header.Get("Content-Type"))
	}
}

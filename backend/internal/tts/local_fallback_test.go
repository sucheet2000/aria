package tts

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"runtime"
	"strings"
	"testing"
)

// Workstream H — the fallback shells out to the macOS `say` binary. On Linux,
// which is where this runs in production, there is no such binary, so the
// fallback could only ever fail. Worse, it is reached after the proxy has
// already failed, at which point the handler has usually written its headers —
// so the failure surfaces as a truncated 200 rather than an error, and the
// browser gets a zero-length audio body with no signal that anything is wrong.

func failingProxy(t *testing.T) *Client {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	t.Cleanup(srv.Close)
	c := New("", "")
	c.SetPythonURL(srv.URL)
	return c
}

// The capability check must be explicit, not "try it and see".
func TestLocalFallback_ReportsWhetherItIsAvailable(t *testing.T) {
	got := localFallbackAvailable()

	switch runtime.GOOS {
	case "darwin":
		// `say` ships with macOS; if it is genuinely missing the check should
		// say so rather than claim availability.
		if got && !haveSayBinary() {
			t.Fatal("claimed availability without the binary present")
		}
	default:
		if got {
			t.Fatalf("claimed the macOS fallback is available on %s", runtime.GOOS)
		}
	}
}

// withoutLocalFallback forces the no-fallback platform behaviour, so the Linux
// path is covered even when the suite runs on macOS.
func withoutLocalFallback(t *testing.T) {
	t.Helper()
	prev := localFallbackCheck
	localFallbackCheck = func() bool { return false }
	t.Cleanup(func() { localFallbackCheck = prev })
}

// On a platform without the fallback, the call must fail with a clear error
// rather than pretending to have produced audio.
func TestStream_WithoutLocalFallback_ReturnsAnError(t *testing.T) {
	withoutLocalFallback(t)
	body, err := drain(t, failingProxy(t), context.Background(), "hello", "")

	if err == nil {
		t.Fatal("no error when neither the proxy nor a fallback could speak")
	}
	if len(body) != 0 {
		t.Fatalf("produced %d bytes of audio it never had", len(body))
	}
	if !strings.Contains(err.Error(), "unavailable") {
		t.Fatalf("error does not explain the situation: %v", err)
	}
}

// The error must name the real cause, so an operator reading a log knows the
// Python service is down rather than chasing a phantom audio bug.
func TestStream_ErrorMentionsTheProxyFailure(t *testing.T) {
	withoutLocalFallback(t)
	_, err := drain(t, failingProxy(t), context.Background(), "hello", "")
	if err == nil {
		t.Fatal("expected an error")
	}
	if !strings.Contains(err.Error(), "503") {
		t.Fatalf("the proxy failure is not visible in the error: %v", err)
	}
}

// The happy path is untouched: a working proxy never reaches the fallback.
func TestStream_ProxySuccessNeverConsultsTheFallback(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Write([]byte("audio-bytes"))
	}))
	defer srv.Close()

	c := New("", "")
	c.SetPythonURL(srv.URL)
	got, err := drain(t, c, context.Background(), "hi", "")
	if err != nil {
		t.Fatalf("proxy path failed: %v", err)
	}
	if got != "audio-bytes" {
		t.Fatalf("got %q", got)
	}
}

// drain reads a client's speech stream to a string, so tests can assert on the
// bytes the handler would forward.
func drain(t *testing.T, c *Client, ctx context.Context, text, emotion string) (string, error) {
	t.Helper()
	rc, err := c.Open(ctx, text, emotion)
	if err != nil {
		return "", err
	}
	defer rc.Close()
	b, readErr := io.ReadAll(rc)
	return string(b), readErr
}

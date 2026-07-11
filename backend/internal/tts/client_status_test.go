package tts

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// TestStreamProxy_Non2xxReturnsMeaningfulError verifies that a non-2xx response
// from the Python TTS service surfaces as a clear status+body error.
func TestStreamProxy_Non2xxReturnsMeaningfulError(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte("elevenlabs quota exceeded"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	var buf bytes.Buffer
	err := c.streamProxy(context.Background(), "hello", "", &buf)
	if err == nil {
		t.Fatal("expected error on 500, got nil")
	}
	msg := err.Error()
	if !strings.Contains(msg, "500") {
		t.Errorf("error should mention status 500, got %q", msg)
	}
	if !strings.Contains(msg, "quota exceeded") {
		t.Errorf("error should include upstream body, got %q", msg)
	}
}

// TestStreamProxy_ErrorBodyIsBounded verifies that a very large upstream error
// body does not blow up the returned error message unbounded.
func TestStreamProxy_ErrorBodyIsBounded(t *testing.T) {
	huge := strings.Repeat("y", 100*1024)
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(huge))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	var buf bytes.Buffer
	err := c.streamProxy(context.Background(), "hello", "", &buf)
	if err == nil {
		t.Fatal("expected error on 502, got nil")
	}
	if len(err.Error()) > 8*1024 {
		t.Errorf("error body not bounded: len=%d (want <= 8KB)", len(err.Error()))
	}
}

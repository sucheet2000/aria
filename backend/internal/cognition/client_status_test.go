package cognition

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/memory"
)

// TestComplete_Non2xxReturnsMeaningfulError verifies that a non-2xx response
// from the Python service surfaces as a clear status+body error rather than a
// confusing "decode cognition response" error.
func TestComplete_Non2xxReturnsMeaningfulError(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"detail":"validation failed"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	_, err := c.Complete(context.Background(), CognitionRequest{Message: "hi", SessionID: "s1"})
	if err == nil {
		t.Fatal("expected error on 422, got nil")
	}
	msg := err.Error()
	if !strings.Contains(msg, "422") {
		t.Errorf("error should mention status 422, got %q", msg)
	}
	if !strings.Contains(msg, "validation failed") {
		t.Errorf("error should include upstream body, got %q", msg)
	}
	if strings.Contains(strings.ToLower(msg), "decode") {
		t.Errorf("error should not be a decode error, got %q", msg)
	}
}

// TestComplete_ErrorBodyIsBounded verifies that a very large upstream error
// body does not blow up the returned error message unbounded.
func TestComplete_ErrorBodyIsBounded(t *testing.T) {
	huge := strings.Repeat("x", 100*1024)
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(huge))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	_, err := c.Complete(context.Background(), CognitionRequest{Message: "hi", SessionID: "s1"})
	if err == nil {
		t.Fatal("expected error on 500, got nil")
	}
	if len(err.Error()) > 8*1024 {
		t.Errorf("error body not bounded: len=%d (want <= 8KB)", len(err.Error()))
	}
}

package cognition

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

func TestClientComplete_SetsOwnerHeader(t *testing.T) {
	var gotOwner string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotOwner = r.Header.Get("X-Aria-Owner")
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctx := auth.WithOwner(context.Background(), "user_owner_1")

	if _, err := c.Complete(ctx, CognitionRequest{Message: "hello", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if gotOwner != "user_owner_1" {
		t.Errorf("X-Aria-Owner = %q, want user_owner_1", gotOwner)
	}
}

func TestClientComplete_NoOwnerHeaderWhenAbsent(t *testing.T) {
	var hadHeader bool
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, hadHeader = r.Header["X-Aria-Owner"]
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))

	if _, err := c.Complete(context.Background(), CognitionRequest{Message: "hello", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if hadHeader {
		t.Error("X-Aria-Owner should not be set when no owner in context")
	}
}

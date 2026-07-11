package cognition

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

func TestClientComplete_ForwardsRequestID(t *testing.T) {
	var got string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get(reqid.Header)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctx := reqid.WithID(context.Background(), "rid-cog-1")

	if _, err := c.Complete(ctx, CognitionRequest{Message: "hello", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if got != "rid-cog-1" {
		t.Errorf("%s = %q, want rid-cog-1", reqid.Header, got)
	}
}

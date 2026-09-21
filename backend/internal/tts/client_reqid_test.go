package tts

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/reqid"
)

func TestStream_ForwardsRequestID(t *testing.T) {
	var got string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get(reqid.Header)
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("audio"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	ctx := reqid.WithID(context.Background(), "rid-tts-1")
	if _, err := drain(t, c, ctx, "hello", ""); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if got != "rid-tts-1" {
		t.Errorf("%s = %q, want rid-tts-1", reqid.Header, got)
	}
}

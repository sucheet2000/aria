package tts

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/auth"
)

func TestStream_SetsOwnerHeader(t *testing.T) {
	var gotOwner string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotOwner = r.Header.Get("X-Aria-Owner")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("audio"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	ctx := auth.WithOwner(context.Background(), "user_tts_1")
	if _, err := drain(t, c, ctx, "hello", ""); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if gotOwner != "user_tts_1" {
		t.Errorf("X-Aria-Owner = %q, want user_tts_1", gotOwner)
	}
}

func TestStream_NoOwnerHeaderWhenAbsent(t *testing.T) {
	var hadHeader bool
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, hadHeader = r.Header["X-Aria-Owner"]
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("audio"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	if _, err := drain(t, c, context.Background(), "hello", ""); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if hadHeader {
		t.Error("X-Aria-Owner should not be set when no owner in context")
	}
}

func TestStream_SetsInternalAuthHeader(t *testing.T) {
	var gotSecret string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Auth")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("audio"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL
	c.SetInternalAuthSecret("boundary-secret")

	if _, err := drain(t, c, context.Background(), "hello", ""); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if gotSecret != "boundary-secret" {
		t.Errorf("X-Internal-Auth = %q, want boundary-secret", gotSecret)
	}
}

func TestStream_NoInternalAuthHeaderWhenSecretEmpty(t *testing.T) {
	var hadHeader bool
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, hadHeader = r.Header["X-Internal-Auth"]
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("audio"))
	}))
	defer fake.Close()

	c := New("", "")
	c.pythonURL = fake.URL

	if _, err := drain(t, c, context.Background(), "hello", ""); err != nil {
		t.Fatalf("Stream: %v", err)
	}
	if hadHeader {
		t.Error("X-Internal-Auth should not be set when secret is empty")
	}
}

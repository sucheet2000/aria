package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestWaitForPython_ReadyReturnsTrue(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	defer ts.Close()

	if !waitForPython(context.Background(), ts.Client(), ts.URL+"/health", 5, 10*time.Millisecond) {
		t.Fatal("expected true when /health is reachable")
	}
}

func TestWaitForPython_UnreachableGivesUp(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := ts.URL
	ts.Close() // now unreachable — connection refused

	start := time.Now()
	if waitForPython(context.Background(), ts.Client(), url+"/health", 3, 10*time.Millisecond) {
		t.Fatal("expected false when /health is unreachable")
	}
	if elapsed := time.Since(start); elapsed > time.Second {
		t.Fatalf("gave up too slowly: %v", elapsed)
	}
}

func TestWaitForPython_CancelledContextReturnsFalse(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	if waitForPython(ctx, http.DefaultClient, "http://127.0.0.1:0/health", 10, time.Second) {
		t.Fatal("expected false when context is already cancelled")
	}
}

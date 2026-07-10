package cognition

import (
	"context"
	"encoding/json"
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

func TestClientComplete_SetsInternalAuthHeader(t *testing.T) {
	var gotSecret string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotSecret = r.Header.Get("X-Internal-Auth")
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	c.SetInternalAuthSecret("boundary-secret")

	if _, err := c.Complete(context.Background(), CognitionRequest{Message: "hello", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if gotSecret != "boundary-secret" {
		t.Errorf("X-Internal-Auth = %q, want boundary-secret", gotSecret)
	}
}

func TestClientComplete_NoInternalAuthHeaderWhenSecretEmpty(t *testing.T) {
	var hadHeader bool
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, hadHeader = r.Header["X-Internal-Auth"]
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))

	if _, err := c.Complete(context.Background(), CognitionRequest{Message: "hello", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete: %v", err)
	}
	if hadHeader {
		t.Error("X-Internal-Auth should not be set when secret is empty")
	}
}

// TestClientComplete_OwnerScopesMemory verifies that one owner's enrichment
// (working + episodic memory) never leaks into another owner's request.
func TestClientComplete_OwnerScopesMemory(t *testing.T) {
	type capture struct {
		working  []string
		episodic []string
	}
	var captures []capture

	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			WorkingMemory  []string `json:"working_memory"`
			EpisodicMemory []string `json:"episodic_memory"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		captures = append(captures, capture{working: body.WorkingMemory, episodic: body.EpisodicMemory})
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"inf-A","natural_language_response":"hi","episodic_memory":["ep-A"]}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctxA := auth.WithOwner(context.Background(), "owner_a")
	ctxB := auth.WithOwner(context.Background(), "owner_b")

	// First call for owner A seeds A's working ("inf-A") and episodic ("ep-A") caches.
	if _, err := c.Complete(ctxA, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete A#1: %v", err)
	}
	// Second call for owner A must carry A's previously cached memory.
	if _, err := c.Complete(ctxA, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete A#2: %v", err)
	}
	// Call for owner B must NOT see any of A's memory.
	if _, err := c.Complete(ctxB, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete B: %v", err)
	}

	if len(captures) != 3 {
		t.Fatalf("expected 3 captured requests, got %d", len(captures))
	}
	if len(captures[1].working) == 0 || captures[1].working[0] != "inf-A" {
		t.Errorf("owner A second call working = %v, want [inf-A]", captures[1].working)
	}
	if len(captures[1].episodic) == 0 || captures[1].episodic[0] != "ep-A" {
		t.Errorf("owner A second call episodic = %v, want [ep-A]", captures[1].episodic)
	}
	if len(captures[2].working) != 0 {
		t.Errorf("owner B working = %v, want empty (no leak from A)", captures[2].working)
	}
	if len(captures[2].episodic) != 0 {
		t.Errorf("owner B episodic = %v, want empty (no leak from A)", captures[2].episodic)
	}
}

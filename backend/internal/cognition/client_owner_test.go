package cognition

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
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

// TestClientComplete_OwnerScopesMemory verifies that one owner's working
// memory enrichment never leaks into another owner's request, and that Go
// sends NO episodic memory at all: Python retrieves it per turn (S3).
func TestClientComplete_OwnerScopesMemory(t *testing.T) {
	type capture struct {
		working     []string
		hasEpisodic bool
	}
	var captures []capture

	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]json.RawMessage
		_ = json.NewDecoder(r.Body).Decode(&body)
		var working []string
		_ = json.Unmarshal(body["working_memory"], &working)
		_, hasEpisodic := body["episodic_memory"]
		captures = append(captures, capture{working: working, hasEpisodic: hasEpisodic})
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"inf-A","natural_language_response":"hi","episodic_memory":["ep-A"]}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctxA := auth.WithOwner(context.Background(), "owner_a")
	ctxB := auth.WithOwner(context.Background(), "owner_b")

	if _, err := c.Complete(ctxA, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete A#1: %v", err)
	}
	if _, err := c.Complete(ctxA, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete A#2: %v", err)
	}
	if _, err := c.Complete(ctxB, CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatalf("Complete B: %v", err)
	}

	if len(captures) != 3 {
		t.Fatalf("expected 3 captured requests, got %d", len(captures))
	}
	if len(captures[1].working) == 0 || captures[1].working[0] != "inf-A" {
		t.Errorf("owner A second call working = %v, want [inf-A]", captures[1].working)
	}
	if len(captures[2].working) != 0 {
		t.Errorf("owner B working = %v, want empty (no leak from A)", captures[2].working)
	}
	for i, cap := range captures {
		if cap.hasEpisodic {
			t.Errorf("request %d carried an episodic_memory field; Go must not supply memory", i)
		}
	}
}

// TestClientComplete_NoStaleEpisodicReplay reproduces the S3 bug: turn 1
// returned memory X; the store was then emptied (turn 2 returns nothing). The
// old replay cache re-sent X on turn 2 and turn 3. Now nothing is ever
// replayed, and an episodic list from Python is passed through to the browser
// only for the turn that produced it.
func TestClientComplete_NoStaleEpisodicReplay(t *testing.T) {
	var bodies []string
	turn := 0
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		bodies = append(bodies, string(raw))
		turn++
		w.Header().Set("Content-Type", "application/json")
		if turn == 1 {
			w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi","episodic_memory":["DELETED_MEMORY_SENTINEL_9137"]}`))
			return
		}
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi","episodic_memory":[]}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctx := auth.WithOwner(context.Background(), "owner_a")

	first, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if err != nil {
		t.Fatal(err)
	}
	if len(first.EpisodicMemory) != 1 {
		t.Fatalf("turn 1 should pass Python's list through, got %v", first.EpisodicMemory)
	}
	for i := 0; i < 2; i++ {
		resp, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
		if err != nil {
			t.Fatal(err)
		}
		if len(resp.EpisodicMemory) != 0 {
			t.Errorf("turn %d replayed stale memory to the browser: %v", i+2, resp.EpisodicMemory)
		}
	}
	for i, b := range bodies {
		if strings.Contains(b, "DELETED_MEMORY_SENTINEL_9137") {
			t.Errorf("request %d re-sent deleted memory to Python: %s", i+1, b)
		}
	}
}

// TestClientComplete_NoPushAfterClearDuringTurn: the owner deletes all memory
// while a cognition turn is in flight. The inference from that turn must not
// be pushed into the freshly cleared working ring.
func TestClientComplete_NoPushAfterClearDuringTurn(t *testing.T) {
	wm := memory.New(5)
	wm.Push("owner_a", "old")
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		wm.Clear("owner_a") // delete-all lands mid-turn
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"late inference","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, wm)
	if _, err := c.Complete(auth.WithOwner(context.Background(), "owner_a"), CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatal(err)
	}
	if got := wm.All("owner_a"); len(got) != 0 {
		t.Fatalf("late inference re-populated cleared working memory: %v", got)
	}
}

package cognition

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// R5: Python's user-safe fallback for a malformed / truncated / empty provider
// turn carries symbolic_inference "" and no world_model_update. Go must push
// nothing into the working ring and derive the neutral avatar emotion — no
// sentinel like "parse error" or raw model text ever becomes working state.
func TestClientComplete_FallbackTurnPushesNothingToRing(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","world_model_update":null,` +
			`"natural_language_response":"Sorry, I lost my train of thought for a moment. Could you say that again?",` +
			`"processing_ms":1,"episodic_memory":[],"spatial_event":null}`))
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	ctx := auth.WithOwner(context.Background(), "owner_a")

	resp, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if err != nil {
		t.Fatal(err)
	}
	if got := wm.All("owner_a"); len(got) != 0 {
		t.Fatalf("fallback turn populated the working ring: %v", got)
	}
	if resp.AvatarEmotion != "neutral" {
		t.Errorf("avatar_emotion = %q, want neutral for an empty inference", resp.AvatarEmotion)
	}
	if resp.WorldModelUpdate != nil {
		t.Errorf("fallback turn carried a world_model_update: %+v", resp.WorldModelUpdate)
	}
	if resp.NaturalLanguageResponse == "" {
		t.Error("fallback turn must still carry the safe spoken text")
	}
}

// R3/R5: a valid symbolic inference still drives the ring and the avatar
// emotion exactly as before.
func TestClientComplete_ValidInferenceStillDrivesRingAndEmotion(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"user is happy and excited about the bike",` +
			`"natural_language_response":"Nice bike!"}`))
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	ctx := auth.WithOwner(context.Background(), "owner_a")

	resp, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if err != nil {
		t.Fatal(err)
	}
	if got := wm.All("owner_a"); len(got) != 1 || got[0] != "user is happy and excited about the bike" {
		t.Fatalf("ring = %v, want the valid inference", got)
	}
	if resp.AvatarEmotion != "happy" {
		t.Errorf("avatar_emotion = %q, want happy", resp.AvatarEmotion)
	}
}

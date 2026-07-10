package cognition

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

func TestCognitionRequest_GestureFieldsDecodedFromJSON(t *testing.T) {
	raw := `{
		"message": "hello",
		"session_id": "test-session",
		"vision_state": {"emotion": "neutral"},
		"gesture": "point",
		"two_hand_gesture": "NONE",
		"pointing_vector": [0.1, 0.2, 0.3]
	}`
	var req CognitionRequest
	if err := json.NewDecoder(strings.NewReader(raw)).Decode(&req); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if req.Gesture != "point" {
		t.Errorf("Gesture = %q, want %q", req.Gesture, "point")
	}
	if req.TwoHandGesture != "NONE" {
		t.Errorf("TwoHandGesture = %q, want %q", req.TwoHandGesture, "NONE")
	}
	if len(req.PointingVector) != 3 {
		t.Fatalf("PointingVector len = %d, want 3", len(req.PointingVector))
	}
	if req.PointingVector[0] != 0.1 || req.PointingVector[1] != 0.2 || req.PointingVector[2] != 0.3 {
		t.Errorf("PointingVector = %v, want [0.1 0.2 0.3]", req.PointingVector)
	}
}

func TestEnrichedRequest_GestureFieldsMarshalled(t *testing.T) {
	req := CognitionRequest{
		Message:        "hello",
		SessionID:      "s1",
		Gesture:        "point",
		TwoHandGesture: "NONE",
		PointingVector: []float64{0.5, -0.5, 0.7},
	}
	enriched := enrichedRequest{
		CognitionRequest: req,
		WorkingMemory:    []string{},
		EpisodicMemory:   []string{},
	}
	b, err := json.Marshal(enriched)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var out map[string]any
	if err := json.Unmarshal(b, &out); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if out["gesture"] != "point" {
		t.Errorf("gesture = %v, want %q", out["gesture"], "point")
	}
	if out["two_hand_gesture"] != "NONE" {
		t.Errorf("two_hand_gesture = %v, want %q", out["two_hand_gesture"], "NONE")
	}
	vec, ok := out["pointing_vector"].([]any)
	if !ok || len(vec) != 3 {
		t.Fatalf("pointing_vector bad shape: %v", out["pointing_vector"])
	}
	if vec[0] != 0.5 || vec[1] != -0.5 || vec[2] != 0.7 {
		t.Errorf("pointing_vector = %v, want [0.5 -0.5 0.7]", vec)
	}
}

func TestCognitionResponse_SpatialEventPassthrough(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{
			"symbolic_inference": "test",
			"natural_language_response": "hi",
			"world_model_update": null,
			"episodic_memory": [],
			"spatial_event": {"type": "anchor_registered", "anchor_id": "abc-123", "payload": {"label": "lamp"}}
		}`))
	}))
	defer fakePython.Close()

	wm := memory.New(5)
	client := NewWithLogger(fakePython.URL, wm, zerolog.Nop())

	resp, err := client.Complete(context.Background(), CognitionRequest{
		Message:   "test",
		SessionID: "s1",
		Gesture:   "point",
	})
	if err != nil {
		t.Fatalf("Complete: %v", err)
	}

	if len(resp.SpatialEvent) == 0 {
		t.Fatal("SpatialEvent is empty, want passthrough from Python")
	}

	var event map[string]any
	if err := json.Unmarshal(resp.SpatialEvent, &event); err != nil {
		t.Fatalf("unmarshal SpatialEvent: %v", err)
	}
	if event["type"] != "anchor_registered" {
		t.Errorf("event type = %v, want %q", event["type"], "anchor_registered")
	}
	if event["anchor_id"] != "abc-123" {
		t.Errorf("anchor_id = %v, want %q", event["anchor_id"], "abc-123")
	}
}

func TestCognitionResponse_SpatialEventNull(t *testing.T) {
	fakePython := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{
			"symbolic_inference": "",
			"natural_language_response": "hi",
			"world_model_update": null,
			"spatial_event": null
		}`))
	}))
	defer fakePython.Close()

	wm := memory.New(5)
	client := NewWithLogger(fakePython.URL, wm, zerolog.Nop())

	resp, err := client.Complete(context.Background(), CognitionRequest{Message: "test", SessionID: "s1"})
	if err != nil {
		t.Fatalf("Complete: %v", err)
	}

	// null spatial_event should decode to "null" bytes or nil — either is acceptable;
	// what matters is that it does NOT cause an error and is safe to omit in the response.
	if string(resp.SpatialEvent) == `{"type":"anchor_registered"}` {
		t.Error("SpatialEvent should not contain anchor data when Python returns null")
	}
}

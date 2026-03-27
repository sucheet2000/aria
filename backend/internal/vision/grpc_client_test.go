package vision

import (
	"encoding/json"
	"testing"

	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
)

type mockBroadcaster struct {
	received [][]byte
}

func (m *mockBroadcaster) Broadcast(data []byte) {
	m.received = append(m.received, data)
}

func TestBroadcastFrame_ProducesVisionStateJSON(t *testing.T) {
	hub := &mockBroadcaster{}
	client := NewGRPCClient(hub)

	frame := &perceptionv1.PerceptionFrame{
		Hands: []*perceptionv1.HandData{
			{
				Landmarks: []*perceptionv1.Point3D{
					{X: 0.1, Y: 0.2, Z: 0.3},
					{X: 0.4, Y: 0.5, Z: 0.6},
				},
			},
		},
	}

	client.broadcastFrame(frame)

	if len(hub.received) != 1 {
		t.Fatalf("expected 1 broadcast, got %d", len(hub.received))
	}

	var msg map[string]interface{}
	if err := json.Unmarshal(hub.received[0], &msg); err != nil {
		t.Fatalf("broadcast is not valid JSON: %v", err)
	}
	if msg["type"] != "vision_state" {
		t.Errorf("expected type=vision_state, got %v", msg["type"])
	}
	payload, ok := msg["payload"].(map[string]interface{})
	if !ok {
		t.Fatalf("payload is not a map, got %T", msg["payload"])
	}
	hands, ok := payload["hand_landmarks"].([]interface{})
	if !ok {
		t.Fatalf("hand_landmarks is not a list, got %T", payload["hand_landmarks"])
	}
	if len(hands) != 2 {
		t.Errorf("expected 2 hand landmarks, got %d", len(hands))
	}
}

func TestBroadcastFrame_EmptyFrameStillBroadcasts(t *testing.T) {
	hub := &mockBroadcaster{}
	client := NewGRPCClient(hub)

	client.broadcastFrame(&perceptionv1.PerceptionFrame{})

	if len(hub.received) != 1 {
		t.Fatalf("expected 1 broadcast even for empty frame, got %d", len(hub.received))
	}
	var msg map[string]interface{}
	if err := json.Unmarshal(hub.received[0], &msg); err != nil {
		t.Fatalf("broadcast not valid JSON: %v", err)
	}
	if msg["type"] != "vision_state" {
		t.Errorf("type should be vision_state, got %v", msg["type"])
	}
}

package server

import "encoding/json"

const (
	MsgTypeVisionState       = "vision_state"
	MsgTypeTranscript        = "transcript"
	MsgTypeARIAResponse      = "aria_response"
	MsgTypeError             = "error"
	MsgTypeSessionInit       = "session_init"
	MsgTypeAnchorRegistered  = "anchor_registered"
	MsgTypeAnchorsBonded     = "anchors_bonded"
	MsgTypeAnchorThrown      = "anchor_thrown"
	MsgTypeWorldExpand       = "world_expand"
)

// SpatialEvent is the WebSocket envelope for spatial anchor events produced
// by the gesture-anchor bridge. Mirrors the Python SpatialEvent dataclass
// and the proto SpatialEvent message.
type SpatialEvent struct {
	EventType string    `json:"event_type"`
	AnchorID  string    `json:"anchor_id,omitempty"`
	AnchorIDs []string  `json:"anchor_ids,omitempty"`
	Velocity  []float64 `json:"velocity,omitempty"`
	Factor    float64   `json:"factor,omitempty"`
}

// WebSocketMessage is the envelope for all messages sent over the WebSocket.
type WebSocketMessage struct {
	Type    string          `json:"type"`
	Payload json.RawMessage `json:"payload"`
}

// NewMessage marshals payload and wraps it in a WebSocketMessage envelope.
func NewMessage(msgType string, payload any) ([]byte, error) {
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	msg := WebSocketMessage{
		Type:    msgType,
		Payload: json.RawMessage(raw),
	}
	return json.Marshal(msg)
}

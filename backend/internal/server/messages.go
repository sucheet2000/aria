package server

import "encoding/json"

const (
	MsgTypeVisionState  = "vision_state"
	MsgTypeTranscript   = "transcript"
	MsgTypeARIAResponse = "aria_response"
	MsgTypeError        = "error"
)

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

package cognition

import (
	"context"
	"encoding/json"

	"github.com/rs/zerolog"
	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"google.golang.org/grpc"
)

// Broadcaster is satisfied by server.Hub — defined here to avoid an import cycle.
type Broadcaster interface {
	Broadcast([]byte)
}

// CognitionGRPCServer implements perceptionv1.CognitionServiceServer.
// It receives CognitionRequests from the Python vision worker and either:
//   - routes interrupt_signal payloads through StreamRegistry → cancels active HTTP calls
//   - broadcasts gesture_event / text_input payloads to WebSocket clients via hub
type CognitionGRPCServer struct {
	perceptionv1.UnimplementedCognitionServiceServer
	registry *StreamRegistry
	hub      Broadcaster
	log      zerolog.Logger
}

// NewCognitionGRPCServer creates a CognitionGRPCServer.
func NewCognitionGRPCServer(registry *StreamRegistry, hub Broadcaster, log zerolog.Logger) *CognitionGRPCServer {
	return &CognitionGRPCServer{registry: registry, hub: hub, log: log}
}

// StreamCognition is the bi-directional stream handler. Python sends CognitionRequests;
// this method dispatches them based on payload type.
func (s *CognitionGRPCServer) StreamCognition(
	stream grpc.BidiStreamingServer[perceptionv1.CognitionRequest, perceptionv1.CognitionResponse],
) error {
	for {
		req, err := stream.Recv()
		if err != nil {
			return err
		}

		switch p := req.Payload.(type) {
		case *perceptionv1.CognitionRequest_InterruptSignal:
			if p.InterruptSignal {
				sessionID := req.SessionId
				if sessionID == "default" {
					s.registry.CancelActive()
				} else {
					s.registry.Cancel(sessionID)
				}
				payload, _ := json.Marshal(map[string]string{
					"type":       "aria_interrupt",
					"session_id": sessionID,
				})
				s.hub.Broadcast(payload)
				s.log.Info().Str("session_id", sessionID).Msg("interrupt signal received — stream cancelled")
			}

		case *perceptionv1.CognitionRequest_GestureEvent:
			payload, _ := json.Marshal(map[string]any{
				"type":    "gesture_event",
				"payload": p.GestureEvent,
			})
			s.hub.Broadcast(payload)

		case *perceptionv1.CognitionRequest_TextInput:
			payload, _ := json.Marshal(map[string]any{
				"type":    "text_input",
				"payload": p.TextInput,
			})
			s.hub.Broadcast(payload)
		}
	}
}

// RegisterAnchor is a stub — spatial anchoring activates in Week 9.
func (s *CognitionGRPCServer) RegisterAnchor(_ context.Context, anchor *perceptionv1.SpatialAnchor) (*perceptionv1.SpatialAnchor, error) {
	return anchor, nil
}

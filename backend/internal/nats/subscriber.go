package nats

import (
	"encoding/json"
	"fmt"

	"github.com/nats-io/nats.go"
	"github.com/rs/zerolog/log"
	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"google.golang.org/protobuf/proto"
)

const maxPendingMsgs = 100

// Broadcaster is the interface the hub satisfies — same as in the vision package.
type Broadcaster interface {
	Broadcast([]byte)
}

// Subscriber subscribes to NATS PerceptionFrames and broadcasts them to the hub.
// Uses DiscardOld pending policy: when the pending queue is full (100 msgs), the
// oldest message is dropped so the subscriber never blocks the publisher.
type Subscriber struct {
	nc   *nats.Conn
	hub  Broadcaster
	sub  *nats.Subscription
	url  string
}

// NewSubscriber creates a Subscriber that broadcasts to hub.
func NewSubscriber(natsURL string, hub Broadcaster) *Subscriber {
	return &Subscriber{url: natsURL, hub: hub}
}

// Connect establishes the NATS connection and starts the subscription.
func (s *Subscriber) Connect() error {
	nc, err := nats.Connect(s.url,
		nats.Name("aria-subscriber"),
		nats.MaxReconnects(-1),
	)
	if err != nil {
		return fmt.Errorf("nats connect %s: %w", s.url, err)
	}
	s.nc = nc

	sub, err := nc.Subscribe(PerceptionSubject, s.handleMsg)
	if err != nil {
		nc.Close()
		return fmt.Errorf("nats subscribe %s: %w", PerceptionSubject, err)
	}

	// DiscardOld: drop oldest when pending buffer exceeds maxPendingMsgs.
	if err := sub.SetPendingLimits(maxPendingMsgs, maxPendingMsgs*1024*10); err != nil {
		log.Warn().Err(err).Msg("failed to set NATS pending limits")
	}

	s.sub = sub
	log.Info().Str("subject", PerceptionSubject).Msg("NATS subscriber connected")
	return nil
}

func (s *Subscriber) handleMsg(msg *nats.Msg) {
	var frame perceptionv1.PerceptionFrame
	if err := proto.Unmarshal(msg.Data, &frame); err != nil {
		log.Warn().Err(err).Msg("failed to unmarshal PerceptionFrame from NATS")
		return
	}
	s.broadcastFrame(&frame)
}

func (s *Subscriber) broadcastFrame(frame *perceptionv1.PerceptionFrame) {
	handLandmarks := [][]float32{}
	for _, hand := range frame.Hands {
		for _, pt := range hand.Landmarks {
			handLandmarks = append(handLandmarks, []float32{pt.X, pt.Y, pt.Z})
		}
	}

	wrapped := map[string]interface{}{
		"type": "vision_state",
		"payload": map[string]interface{}{
			"face_landmarks": []interface{}{},
			"hand_landmarks": handLandmarks,
			"emotion":        "neutral",
			"head_pose":      map[string]float32{"pitch": 0, "yaw": 0, "roll": 0},
		},
	}
	data, err := json.Marshal(wrapped)
	if err != nil {
		return
	}
	s.hub.Broadcast(data)
}

// Close unsubscribes and closes the NATS connection.
func (s *Subscriber) Close() {
	if s.sub != nil {
		s.sub.Unsubscribe() //nolint:errcheck
	}
	if s.nc != nil {
		s.nc.Close()
	}
}

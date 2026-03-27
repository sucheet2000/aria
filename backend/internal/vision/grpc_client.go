package vision

import (
	"context"
	"encoding/json"
	"time"

	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

const visionGRPCAddr = "localhost:50051"

// GRPCClient connects to the Python vision gRPC server and streams
// PerceptionFrame messages, broadcasting them to the hub.
// It reuses the Broadcaster interface already defined in worker.go.
type GRPCClient struct {
	hub    Broadcaster
	cancel context.CancelFunc
}

// NewGRPCClient creates a GRPCClient that will broadcast to hub.
func NewGRPCClient(hub Broadcaster) *GRPCClient {
	return &GRPCClient{hub: hub}
}

// Start connects to the Python vision server and streams frames.
// Retries with 2s backoff on disconnect. Blocks until ctx is cancelled.
func (c *GRPCClient) Start(ctx context.Context) error {
	ctx, c.cancel = context.WithCancel(ctx)
	for {
		if err := c.stream(ctx); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			log.Warn().Err(err).Msg("vision gRPC stream disconnected, retrying in 2s")
			select {
			case <-time.After(2 * time.Second):
			case <-ctx.Done():
				return nil
			}
		}
	}
}

func (c *GRPCClient) stream(ctx context.Context) error {
	conn, err := grpc.NewClient(visionGRPCAddr,
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		return err
	}
	defer conn.Close()

	client := perceptionv1.NewPerceptionServiceClient(conn)
	stream, err := client.StreamFrames(ctx, &perceptionv1.StreamRequest{
		SessionId: "local",
	})
	if err != nil {
		return err
	}

	log.Info().Str("addr", visionGRPCAddr).Msg("vision gRPC stream connected")
	for {
		frame, err := stream.Recv()
		if err != nil {
			return err
		}
		c.broadcastFrame(frame)
	}
}

// broadcastFrame converts a PerceptionFrame to the existing JSON vision_state
// format so the hub and frontend require zero changes this sprint.
func (c *GRPCClient) broadcastFrame(frame *perceptionv1.PerceptionFrame) {
	// Flatten all hand landmarks into a single list — matches the existing
	// stdout JSON shape the frontend already consumes.
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
	c.hub.Broadcast(data)
}

// Stop cancels the streaming context, causing Start to return.
func (c *GRPCClient) Stop() {
	if c.cancel != nil {
		c.cancel()
	}
}

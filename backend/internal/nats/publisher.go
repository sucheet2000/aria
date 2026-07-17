package nats

import (
	"fmt"
	"math"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/rs/zerolog/log"
	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"google.golang.org/protobuf/proto"
)

const PerceptionSubject = "aria.perception.frames"

// Publisher publishes PerceptionFrame protos to NATS.
// Uses DiscardOld semantics: slow subscribers drop old frames, not new ones.
type Publisher struct {
	nc  *nats.Conn
	url string
}

// NewPublisher creates a Publisher that connects to natsURL.
// Call Connect() before PublishFrame().
func NewPublisher(natsURL string) *Publisher {
	return &Publisher{url: natsURL}
}

// Connect establishes the NATS connection with exponential backoff.
// Blocks until connected or ctx is cancelled (via nats.Options).
func (p *Publisher) Connect() error {
	opts := []nats.Option{
		nats.Name("aria-publisher"),
		nats.ReconnectWait(time.Second),
		nats.MaxReconnects(-1), // unlimited
		nats.CustomReconnectDelay(func(attempts int) time.Duration {
			backoff := time.Duration(math.Pow(2, float64(attempts))) * time.Second
			if backoff > 30*time.Second {
				backoff = 30 * time.Second
			}
			return backoff
		}),
		nats.DisconnectErrHandler(func(_ *nats.Conn, err error) {
			if err != nil {
				log.Warn().Err(err).Msg("NATS publisher disconnected")
			}
		}),
		nats.ReconnectHandler(func(_ *nats.Conn) {
			log.Info().Msg("NATS publisher reconnected")
		}),
	}

	nc, err := nats.Connect(p.url, opts...)
	if err != nil {
		return fmt.Errorf("nats connect %s: %w", p.url, err)
	}
	p.nc = nc
	log.Info().Str("url", p.url).Msg("NATS publisher connected")
	return nil
}

// PublishFrame serializes frame to protobuf bytes and publishes to PerceptionSubject.
func (p *Publisher) PublishFrame(frame *perceptionv1.PerceptionFrame) error {
	if p.nc == nil {
		return fmt.Errorf("nats publisher not connected")
	}
	data, err := proto.Marshal(frame)
	if err != nil {
		return fmt.Errorf("marshal PerceptionFrame: %w", err)
	}
	return p.nc.Publish(PerceptionSubject, data)
}

// Close drains and closes the NATS connection.
func (p *Publisher) Close() {
	if p.nc != nil {
		p.nc.Drain() //nolint:errcheck
	}
}

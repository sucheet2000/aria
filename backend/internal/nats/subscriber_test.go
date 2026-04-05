package nats

import (
	"fmt"
	"sync"
	"testing"
	"time"

	natsgo "github.com/nats-io/nats.go"
	natss "github.com/nats-io/nats-server/v2/server"
	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"google.golang.org/protobuf/proto"
)

// testBroadcaster records every Broadcast call. Thread-safe.
type testBroadcaster struct {
	mu   sync.Mutex
	msgs [][]byte
}

func (b *testBroadcaster) Broadcast(data []byte) {
	b.mu.Lock()
	defer b.mu.Unlock()
	cp := make([]byte, len(data))
	copy(cp, data)
	b.msgs = append(b.msgs, cp)
}

func (b *testBroadcaster) count() int {
	b.mu.Lock()
	defer b.mu.Unlock()
	return len(b.msgs)
}

// startEmbeddedNATSServer starts an embedded NATS server on the given port and
// waits up to 5 s for it to be ready. The server is NOT stopped automatically —
// callers must call Shutdown() themselves (or use defer).
func startEmbeddedNATSServer(t *testing.T, port int) *natss.Server {
	t.Helper()
	opts := &natss.Options{
		Port:  port,
		NoLog: true,
		NoSigs: true,
	}
	ns, err := natss.NewServer(opts)
	if err != nil {
		t.Fatalf("embedded NATS server create: %v", err)
	}
	go ns.Start()
	if !ns.ReadyForConnections(5 * time.Second) {
		t.Fatal("embedded NATS server not ready within 5 s")
	}
	return ns
}

// publishPerceptionFrame marshals an empty PerceptionFrame and publishes it to
// PerceptionSubject on the given connection, then flushes.
func publishPerceptionFrame(t *testing.T, nc *natsgo.Conn) {
	t.Helper()
	frame := &perceptionv1.PerceptionFrame{
		Hands: []*perceptionv1.HandData{
			{
				Landmarks: []*perceptionv1.Point3D{
					{X: 0.1, Y: 0.2, Z: 0.3},
				},
			},
		},
	}
	data, err := proto.Marshal(frame)
	if err != nil {
		t.Fatalf("proto.Marshal PerceptionFrame: %v", err)
	}
	if err := nc.Publish(PerceptionSubject, data); err != nil {
		t.Fatalf("nats publish: %v", err)
	}
	if err := nc.Flush(); err != nil {
		t.Fatalf("nats flush: %v", err)
	}
}

// waitForBroadcasts polls hub until at least want broadcasts have been received
// or the deadline elapses. Fails the test if the count is not reached.
func waitForBroadcasts(t *testing.T, hub *testBroadcaster, want int, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if hub.count() >= want {
			return
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %d broadcasts; got %d", want, hub.count())
}

// waitForReconnect polls sub.nc.IsConnected() for up to timeout, then fails.
// Accessible because this file is in the same package as subscriber.go.
func waitForReconnect(t *testing.T, sub *Subscriber, timeout time.Duration) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if sub.nc != nil && sub.nc.IsConnected() {
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	t.Fatal("subscriber did not reconnect within 5 s")
}

// TestSubscriberReconnectsAfterServerRestart is the Week 10 reconnect regression
// test. It verifies:
//
//  1. Subscriber receives messages from the initial server.
//  2. After the server shuts down and restarts on the same port, the subscriber
//     reconnects within 5 seconds.
//  3. Messages resume flowing after reconnect.
func TestSubscriberReconnectsAfterServerRestart(t *testing.T) {
	const port = 14322
	url := fmt.Sprintf("nats://127.0.0.1:%d", port)

	// ── step 1: start server and connect subscriber ──────────────────────────
	ns1 := startEmbeddedNATSServer(t, port)

	hub := &testBroadcaster{}
	sub := NewSubscriber(url, hub)
	if err := sub.Connect(); err != nil {
		ns1.Shutdown()
		t.Fatalf("subscriber.Connect: %v", err)
	}
	defer sub.Close()

	// ── step 2: publish one message; confirm it arrives ──────────────────────
	pubNC, err := natsgo.Connect(url)
	if err != nil {
		ns1.Shutdown()
		t.Fatalf("publisher connect (before shutdown): %v", err)
	}
	publishPerceptionFrame(t, pubNC)
	pubNC.Close()

	waitForBroadcasts(t, hub, 1, 2*time.Second)
	countBeforeShutdown := hub.count()

	// ── step 3: stop server ──────────────────────────────────────────────────
	ns1.Shutdown()
	// Allow the client-side disconnect to propagate before the port is released.
	time.Sleep(300 * time.Millisecond)

	// ── step 4: restart server on the same port ──────────────────────────────
	ns2 := startEmbeddedNATSServer(t, port)
	defer ns2.Shutdown()

	// ── step 5: verify subscriber reconnects within 5 seconds ────────────────
	waitForReconnect(t, sub, 5*time.Second)

	// Allow the re-subscribe handshake to complete before publishing.
	time.Sleep(200 * time.Millisecond)

	// ── step 6: verify messages resume after reconnect ───────────────────────
	pubNC2, err := natsgo.Connect(url)
	if err != nil {
		t.Fatalf("publisher connect (after restart): %v", err)
	}
	defer pubNC2.Close()

	publishPerceptionFrame(t, pubNC2)
	waitForBroadcasts(t, hub, countBeforeShutdown+1, 3*time.Second)
}

// TestSubscriberInitialConnection verifies Connect() succeeds and a message
// published immediately after is delivered to the broadcaster.
func TestSubscriberInitialConnection(t *testing.T) {
	const port = 14323
	url := fmt.Sprintf("nats://127.0.0.1:%d", port)

	ns := startEmbeddedNATSServer(t, port)
	defer ns.Shutdown()

	hub := &testBroadcaster{}
	sub := NewSubscriber(url, hub)
	if err := sub.Connect(); err != nil {
		t.Fatalf("subscriber.Connect: %v", err)
	}
	defer sub.Close()

	pubNC, err := natsgo.Connect(url)
	if err != nil {
		t.Fatalf("publisher connect: %v", err)
	}
	defer pubNC.Close()

	publishPerceptionFrame(t, pubNC)
	waitForBroadcasts(t, hub, 1, 2*time.Second)
}

// TestSubscriberClose verifies that Close() does not panic when called on a
// connected subscriber.
func TestSubscriberClose(t *testing.T) {
	const port = 14324
	url := fmt.Sprintf("nats://127.0.0.1:%d", port)

	ns := startEmbeddedNATSServer(t, port)
	defer ns.Shutdown()

	hub := &testBroadcaster{}
	sub := NewSubscriber(url, hub)
	if err := sub.Connect(); err != nil {
		t.Fatalf("subscriber.Connect: %v", err)
	}
	sub.Close() // must not panic
}

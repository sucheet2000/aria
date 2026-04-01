package cognition

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"testing"
	"time"

	perceptionv1 "github.com/sucheet2000/aria/backend/gen/go/perception/v1"
	"github.com/rs/zerolog"
	"google.golang.org/grpc/metadata"
)

// --- mock broadcaster ---

type mockBroadcaster struct {
	messages [][]byte
}

func (m *mockBroadcaster) Broadcast(msg []byte) {
	m.messages = append(m.messages, msg)
}

// --- fake bidi stream ---

type fakeStreamCognitionServer struct {
	recv []*perceptionv1.CognitionRequest
	pos  int
}

func (f *fakeStreamCognitionServer) Recv() (*perceptionv1.CognitionRequest, error) {
	if f.pos >= len(f.recv) {
		return nil, errors.New("EOF")
	}
	req := f.recv[f.pos]
	f.pos++
	return req, nil
}

func (f *fakeStreamCognitionServer) Send(*perceptionv1.CognitionResponse) error { return nil }
func (f *fakeStreamCognitionServer) SetHeader(metadata.MD) error                { return nil }
func (f *fakeStreamCognitionServer) SendHeader(metadata.MD) error               { return nil }
func (f *fakeStreamCognitionServer) SetTrailer(metadata.MD)                     {}
func (f *fakeStreamCognitionServer) Context() context.Context                   { return context.Background() }
func (f *fakeStreamCognitionServer) SendMsg(m any) error                        { return nil }
func (f *fakeStreamCognitionServer) RecvMsg(m any) error                        { return nil }

// --- StreamRegistry tests ---

func TestRegistryInterruptCancelsRegisteredStream(t *testing.T) {
	reg := NewStreamRegistry()
	cancelled := false
	reg.Register("sess-1", func() { cancelled = true })
	reg.Cancel("sess-1")
	if !cancelled {
		t.Fatal("expected cancel func to be called")
	}
}

func TestRegistryInterruptNoSession(t *testing.T) {
	// Cancel on an unknown session must not panic.
	reg := NewStreamRegistry()
	reg.Cancel("unknown") // no-op, stores pending
	// Should not panic — test passes if we reach here.
}

func TestRegistryCancelCycle(t *testing.T) {
	reg := NewStreamRegistry()

	first := false
	reg.Register("sess-2", func() { first = true })
	reg.Cancel("sess-2")
	if !first {
		t.Fatal("first cancel not called")
	}

	// Re-register after unregister — stale entry must not interfere.
	reg.Unregister("sess-2")
	second := false
	reg.Register("sess-2", func() { second = true })
	if second {
		t.Fatal("second cancel should not have been called at registration time")
	}
	reg.Cancel("sess-2")
	if !second {
		t.Fatal("second cancel not called")
	}
}

func TestRegistryPendingCancelBeforeRegister(t *testing.T) {
	// Interrupt arrives BEFORE HTTP handler calls Register.
	reg := NewStreamRegistry()
	reg.Cancel("early") // stores pending
	called := false
	reg.Register("early", func() { called = true }) // should fire immediately
	if !called {
		t.Fatal("pending cancel should have fired on Register")
	}
}

// --- CognitionGRPCServer tests ---

func TestInterruptSignalCancelsStreamAndBroadcasts(t *testing.T) {
	reg := NewStreamRegistry()
	hub := &mockBroadcaster{}
	srv := NewCognitionGRPCServer(reg, hub, zerolog.Nop())

	cancelled := false
	reg.Register("test-session", func() { cancelled = true })

	stream := &fakeStreamCognitionServer{
		recv: []*perceptionv1.CognitionRequest{
			{
				SessionId: "test-session",
				Payload:   &perceptionv1.CognitionRequest_InterruptSignal{InterruptSignal: true},
			},
		},
	}
	srv.StreamCognition(stream) //nolint:errcheck — returns EOF after last message

	if !cancelled {
		t.Fatal("expected stream cancel func to be called on interrupt")
	}
	if len(hub.messages) == 0 {
		t.Fatal("expected broadcast after interrupt")
	}

	var msg map[string]string
	if err := json.Unmarshal(hub.messages[0], &msg); err != nil {
		t.Fatalf("broadcast message is not valid JSON: %v", err)
	}
	if msg["type"] != "aria_interrupt" {
		t.Fatalf("expected type=aria_interrupt, got %q", msg["type"])
	}
	if msg["session_id"] != "test-session" {
		t.Fatalf("expected session_id=test-session, got %q", msg["session_id"])
	}
}

func TestRegistryCancelActive(t *testing.T) {
	reg := NewStreamRegistry()

	cancelled := false
	reg.Register("sess-a", func() { cancelled = true })

	id := reg.CancelActive()
	if !cancelled {
		t.Fatal("CancelActive should cancel the most recently registered session")
	}
	if id != "sess-a" {
		t.Fatalf("expected CancelActive to return sess-a, got %q", id)
	}
}

func TestRegistryCancelActiveNoOp(t *testing.T) {
	reg := NewStreamRegistry()
	// No active session — must return "" and not panic.
	id := reg.CancelActive()
	if id != "" {
		t.Fatalf("expected empty return from CancelActive with no active session, got %q", id)
	}
}

func TestCancelActiveAfterUnregister(t *testing.T) {
	reg := NewStreamRegistry()
	reg.Register("sess-a", func() {})
	reg.Unregister("sess-a")

	id := reg.CancelActive()
	if id != "" {
		t.Fatalf("CancelActive should return \"\" after session is unregistered, got %q", id)
	}
}

func TestCancelClearsActiveSession(t *testing.T) {
	reg := NewStreamRegistry()
	reg.Register("sess-a", func() {})
	reg.Cancel("sess-a")

	id := reg.CancelActive()
	if id != "" {
		t.Fatalf("CancelActive should return \"\" after session is cancelled, got %q", id)
	}
}

func TestInterruptWithDefaultSessionRejected(t *testing.T) {
	reg := NewStreamRegistry()
	hub := &mockBroadcaster{}
	srv := NewCognitionGRPCServer(reg, hub, zerolog.Nop())

	cancelled := false
	reg.Register("active-session", func() { cancelled = true })

	stream := &fakeStreamCognitionServer{
		recv: []*perceptionv1.CognitionRequest{
			{
				SessionId: "default",
				Payload:   &perceptionv1.CognitionRequest_InterruptSignal{InterruptSignal: true},
			},
		},
	}
	err := srv.StreamCognition(stream)

	if err == nil {
		t.Fatal("expected InvalidArgument error for interrupt with session_id=default")
	}
	if cancelled {
		t.Fatal("active session must not be cancelled when interrupt is rejected")
	}
	if len(hub.messages) != 0 {
		t.Fatal("no broadcast expected for rejected interrupt")
	}
}

func TestInterruptWithEmptySessionRejected(t *testing.T) {
	reg := NewStreamRegistry()
	hub := &mockBroadcaster{}
	srv := NewCognitionGRPCServer(reg, hub, zerolog.Nop())

	cancelled := false
	reg.Register("active-session", func() { cancelled = true })

	stream := &fakeStreamCognitionServer{
		recv: []*perceptionv1.CognitionRequest{
			{
				SessionId: "",
				Payload:   &perceptionv1.CognitionRequest_InterruptSignal{InterruptSignal: true},
			},
		},
	}
	err := srv.StreamCognition(stream)

	if err == nil {
		t.Fatal("expected InvalidArgument error for interrupt with empty session_id")
	}
	if cancelled {
		t.Fatal("active session must not be cancelled when interrupt is rejected")
	}
	if len(hub.messages) != 0 {
		t.Fatal("no broadcast expected for rejected interrupt")
	}
}

func TestPendingEvictionOnMutation(t *testing.T) {
	reg := NewStreamRegistry()

	// Fill pending map to capacity.
	for i := range maxPendingSize {
		reg.Cancel(fmt.Sprintf("unknown-%d", i))
	}
	if len(reg.pending) != maxPendingSize {
		t.Fatalf("expected %d pending entries, got %d", maxPendingSize, len(reg.pending))
	}

	// One more Cancel must evict the oldest and keep size at maxPendingSize.
	reg.Cancel("overflow")
	if len(reg.pending) != maxPendingSize {
		t.Fatalf("pending map should stay at %d after overflow, got %d", maxPendingSize, len(reg.pending))
	}
}

func TestDuplicateCancelDoesNotEvictOtherPending(t *testing.T) {
	reg := NewStreamRegistry()

	// Fill pending map to capacity with unique IDs.
	for i := range maxPendingSize {
		reg.Cancel(fmt.Sprintf("unique-%d", i))
	}
	if len(reg.pending) != maxPendingSize {
		t.Fatalf("expected %d pending entries, got %d", maxPendingSize, len(reg.pending))
	}

	// Repeatedly cancel the same already-pending ID — must not evict any other entry.
	for range 5 {
		reg.Cancel("unique-0")
	}
	if len(reg.pending) != maxPendingSize {
		t.Fatalf("duplicate Cancel must not grow or shrink pending map, got %d", len(reg.pending))
	}
	// All original IDs must still be present.
	for i := range maxPendingSize {
		id := fmt.Sprintf("unique-%d", i)
		if _, ok := reg.pending[id]; !ok {
			t.Fatalf("pending entry %q was evicted by a duplicate Cancel", id)
		}
	}
}

func TestStalePendingClearedByRegister(t *testing.T) {
	reg := NewStreamRegistry()

	// Manually insert a stale pending entry.
	reg.mu.Lock()
	reg.pending["stale"] = pendingEntry{setAt: time.Now().Add(-(pendingTTL + time.Second))}
	reg.mu.Unlock()

	// Register a different session — eviction runs on every mutation.
	reg.Register("other-session", func() {})

	reg.mu.Lock()
	_, still := reg.pending["stale"]
	reg.mu.Unlock()

	if still {
		t.Fatal("stale pending entry should have been evicted on Register")
	}
}

func TestInterruptSignalFalseIsNoOp(t *testing.T) {
	reg := NewStreamRegistry()
	hub := &mockBroadcaster{}
	srv := NewCognitionGRPCServer(reg, hub, zerolog.Nop())

	stream := &fakeStreamCognitionServer{
		recv: []*perceptionv1.CognitionRequest{
			{
				SessionId: "sess",
				Payload:   &perceptionv1.CognitionRequest_InterruptSignal{InterruptSignal: false},
			},
		},
	}
	srv.StreamCognition(stream) //nolint:errcheck

	if len(hub.messages) != 0 {
		t.Fatal("interrupt_signal=false must not broadcast")
	}
}

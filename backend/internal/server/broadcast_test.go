package server

import (
	"context"
	"testing"
	"time"
)

func addClient(hub *Hub, owner string) *Client {
	c := &Client{owner: owner, send: make(chan []byte, 8)}
	hub.mu.Lock()
	hub.clients[c] = true
	hub.mu.Unlock()
	return c
}

func expectReceive(t *testing.T, c *Client, want string) {
	t.Helper()
	select {
	case got := <-c.send:
		if string(got) != want {
			t.Fatalf("received %q, want %q", got, want)
		}
	case <-time.After(time.Second):
		t.Fatalf("owner %q did not receive expected message %q", c.owner, want)
	}
}

func expectNoReceive(t *testing.T, c *Client) {
	t.Helper()
	select {
	case leaked := <-c.send:
		t.Fatalf("owner %q leaked message: %q", c.owner, leaked)
	case <-time.After(200 * time.Millisecond):
	}
}

func TestBroadcastToOwner_OnlyMatchingOwner(t *testing.T) {
	hub := NewHub()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go hub.Run(ctx)

	a := addClient(hub, "a")
	b := addClient(hub, "b")

	hub.BroadcastToOwner("a", []byte("hi-a"))

	expectReceive(t, a, "hi-a")
	expectNoReceive(t, b)
}

// TestBroadcastToOwner_EmptyOwnerIsAuthDisabledDefault: with auth disabled every
// client carries the empty owner, so an empty-owner transcript reaches all of
// them — and never a client that does carry an owner.
func TestBroadcastToOwner_EmptyOwnerIsAuthDisabledDefault(t *testing.T) {
	hub := NewHub()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go hub.Run(ctx)

	local1 := addClient(hub, "")
	local2 := addClient(hub, "")
	authed := addClient(hub, "a")

	hub.BroadcastToOwner("", []byte("frame"))

	expectReceive(t, local1, "frame")
	expectReceive(t, local2, "frame")
	expectNoReceive(t, authed)
}

func TestBroadcast_UnscopedReachesAll(t *testing.T) {
	hub := NewHub()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go hub.Run(ctx)

	a := addClient(hub, "a")
	b := addClient(hub, "b")

	hub.Broadcast([]byte("all"))

	expectReceive(t, a, "all")
	expectReceive(t, b, "all")
}

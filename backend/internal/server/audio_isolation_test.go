package server

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/sucheet2000/aria/backend/internal/audio"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// ownerAudio is a fake owner-keyed AudioController that records every call
// with the owner the edge attributed it to.
type ownerAudio struct {
	mu         sync.Mutex
	acquired   []string
	released   []string
	frames     map[string][][]byte
	muted      map[string]bool
	holders    map[string]map[string]bool
	acquireErr error
}

func newOwnerAudio() *ownerAudio {
	return &ownerAudio{
		frames:  make(map[string][][]byte),
		muted:   make(map[string]bool),
		holders: make(map[string]map[string]bool),
	}
}

func (o *ownerAudio) Acquire(owner string) error {
	o.mu.Lock()
	defer o.mu.Unlock()
	if o.acquireErr != nil {
		return o.acquireErr
	}
	o.acquired = append(o.acquired, owner)
	return nil
}

func (o *ownerAudio) Release(owner string) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.released = append(o.released, owner)
}

func (o *ownerAudio) WriteAudio(owner string, pcm []byte) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.frames[owner] = append(o.frames[owner], append([]byte(nil), pcm...))
}

func (o *ownerAudio) SetMuted(owner, holder string, muted bool) {
	o.mu.Lock()
	defer o.mu.Unlock()
	if o.holders[owner] == nil {
		o.holders[owner] = make(map[string]bool)
	}
	if muted {
		o.holders[owner][holder] = true
	} else {
		delete(o.holders[owner], holder)
	}
	// The fake mirrors the real rule: muted while any connection holds.
	o.muted[owner] = len(o.holders[owner]) > 0
}

func (o *ownerAudio) ReleaseMuteHolder(owner, holder string) {
	o.SetMuted(owner, holder, false)
}

// holderCount reports how many connections hold owner's mute in the fake.
func (o *ownerAudio) holderCount(owner string) int {
	o.mu.Lock()
	defer o.mu.Unlock()
	return len(o.holders[owner])
}

func (o *ownerAudio) framesFor(owner string) [][]byte {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([][]byte(nil), o.frames[owner]...)
}

func (o *ownerAudio) mutedFor(owner string) (bool, bool) {
	o.mu.Lock()
	defer o.mu.Unlock()
	v, ok := o.muted[owner]
	return v, ok
}

func (o *ownerAudio) releasedList() []string {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]string(nil), o.released...)
}

func (o *ownerAudio) acquiredList() []string {
	o.mu.Lock()
	defer o.mu.Unlock()
	return append([]string(nil), o.acquired...)
}

// ownerVerifier maps token → owner so two clients can authenticate as
// different users against one test server.
type ownerVerifier map[string]string

func (v ownerVerifier) Verify(_ context.Context, token string) (string, error) {
	if owner, ok := v[token]; ok {
		return owner, nil
	}
	return "", http.ErrNoCookie
}

// startIsolationServer serves both /ws and /ws/audio on one hub with the
// owner-keyed fake controller.
func startIsolationServer(t *testing.T, verifier auth.Verifier, authEnabled bool, fake *ownerAudio) (*httptest.Server, *Hub) {
	t.Helper()
	hub := NewHub()
	hub.SetAudio(fake)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		ServeWs(hub, verifier, authEnabled, testOrigins, w, r)
	})
	mux.HandleFunc("/ws/audio", func(w http.ResponseWriter, r *http.Request) {
		ServeAudioWs(hub, verifier, authEnabled, testOrigins, w, r)
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	return srv, hub
}

func dialPath(t *testing.T, base, path, token string) *websocket.Conn {
	t.Helper()
	u := "ws" + base[len("http"):] + path
	header := http.Header{}
	header.Set("Origin", "http://localhost:3000")
	dialer := *websocket.DefaultDialer
	if token != "" {
		dialer.Subprotocols = []string{wsSubprotocol, token}
	}
	conn, resp, err := dialer.Dial(u, header)
	if err != nil {
		t.Fatalf("dial %s: %v (status %d)", path, err, statusOf(resp))
	}
	t.Cleanup(func() { conn.Close() })
	return conn
}

func waitUntil(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if cond() {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", what)
}

func readText(t *testing.T, conn *websocket.Conn, timeout time.Duration) (string, bool) {
	t.Helper()
	conn.SetReadDeadline(time.Now().Add(timeout))
	_, msg, err := conn.ReadMessage()
	if err != nil {
		return "", false
	}
	return string(msg), true
}

var twoUsers = ownerVerifier{"tok-a": "a", "tok-b": "b"}

// Test 2 / Test 4 (edge): interleaved frames from two authenticated audio
// sockets are attributed to their own owners, and B connecting after A does
// not change how A's frames are attributed.
func TestAudioWs_InterleavedFramesAttributedToOwnConnectionOwner(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t, twoUsers, true, fake)

	a := dialPath(t, srv.URL, "/ws/audio", "tok-a")
	if err := a.WriteMessage(websocket.BinaryMessage, []byte("A1")); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "A1 forwarded", func() bool { return len(fake.framesFor("a")) == 1 })

	// B connects second — the former activeOwner bug would now reroute A.
	b := dialPath(t, srv.URL, "/ws/audio", "tok-b")
	for _, f := range []struct {
		c    *websocket.Conn
		data string
	}{{b, "B1"}, {a, "A2"}, {b, "B2"}} {
		if err := f.c.WriteMessage(websocket.BinaryMessage, []byte(f.data)); err != nil {
			t.Fatal(err)
		}
	}
	waitUntil(t, "all frames forwarded", func() bool {
		return len(fake.framesFor("a")) == 2 && len(fake.framesFor("b")) == 2
	})

	if got := fake.framesFor("a"); string(got[0]) != "A1" || string(got[1]) != "A2" {
		t.Fatalf("owner a frames = %q, want [A1 A2]", got)
	}
	if got := fake.framesFor("b"); string(got[0]) != "B1" || string(got[1]) != "B2" {
		t.Fatalf("owner b frames = %q, want [B1 B2]", got)
	}
	if got := fake.acquiredList(); len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatalf("acquired = %v, want [a b]", got)
	}
}

// Test 4 (routing): a transcript produced for owner a reaches only a's /ws
// clients, regardless of b having connected later and sent session_init.
func TestAudioWs_TranscriptRoutingUnaffectedByLaterSession(t *testing.T) {
	fake := newOwnerAudio()
	srv, hub := startIsolationServer(t, twoUsers, true, fake)

	wsA := dialPath(t, srv.URL, "/ws", "tok-a")
	_ = dialPath(t, srv.URL, "/ws/audio", "tok-a")
	waitForClients(t, hub, 1)

	wsB := dialPath(t, srv.URL, "/ws", "tok-b")
	_ = dialPath(t, srv.URL, "/ws/audio", "tok-b")
	waitForClients(t, hub, 2)
	if err := wsB.WriteMessage(websocket.TextMessage, []byte(`{"type":"session_init","session_id":"s-b"}`)); err != nil {
		t.Fatal(err)
	}
	time.Sleep(50 * time.Millisecond)

	// This is what the manager's router does for a transcript from a's worker.
	hub.BroadcastToOwner("a", []byte(`{"type":"transcript","payload":{"transcript":"hello from A"}}`))

	if got, ok := readText(t, wsA, time.Second); !ok || got != `{"type":"transcript","payload":{"transcript":"hello from A"}}` {
		t.Fatalf("A did not receive its transcript, got %q ok=%v", got, ok)
	}
	if got, ok := readText(t, wsB, 200*time.Millisecond); ok {
		t.Fatalf("B received A's transcript: %q", got)
	}
}

// Test 3 (edge): tts_mute from owner a's /ws mutes only a; b is untouched.
func TestWs_TtsMuteIsScopedToSendingOwner(t *testing.T) {
	fake := newOwnerAudio()
	srv, hub := startIsolationServer(t, twoUsers, true, fake)

	wsA := dialPath(t, srv.URL, "/ws", "tok-a")
	_ = dialPath(t, srv.URL, "/ws", "tok-b")
	waitForClients(t, hub, 2)

	if err := wsA.WriteMessage(websocket.TextMessage, []byte(`{"type":"tts_mute"}`)); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "a muted", func() bool { m, ok := fake.mutedFor("a"); return ok && m })
	if _, ok := fake.mutedFor("b"); ok {
		t.Fatal("b's mute state was touched by a's tts_mute")
	}

	if err := wsA.WriteMessage(websocket.TextMessage, []byte(`{"type":"tts_unmute"}`)); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "a unmuted", func() bool { m, ok := fake.mutedFor("a"); return ok && !m })
	if _, ok := fake.mutedFor("b"); ok {
		t.Fatal("b's mute state was touched by a's tts_unmute")
	}
}

// Test 7: a client-supplied owner field can never redirect mute or routing;
// the authenticated connection identity wins.
func TestWs_ClientSuppliedOwnerIsIgnored(t *testing.T) {
	fake := newOwnerAudio()
	srv, hub := startIsolationServer(t, twoUsers, true, fake)

	wsA := dialPath(t, srv.URL, "/ws", "tok-a")
	wsB := dialPath(t, srv.URL, "/ws", "tok-b")
	waitForClients(t, hub, 2)

	if err := wsB.WriteMessage(websocket.TextMessage, []byte(`{"type":"tts_mute","owner":"a","user_id":"a"}`)); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "b muted", func() bool { m, ok := fake.mutedFor("b"); return ok && m })
	if _, ok := fake.mutedFor("a"); ok {
		t.Fatal("client-supplied owner field redirected mute to a")
	}

	if err := wsB.WriteMessage(websocket.TextMessage, []byte(`{"type":"session_init","session_id":"x","owner":"a"}`)); err != nil {
		t.Fatal(err)
	}
	time.Sleep(50 * time.Millisecond)
	hub.BroadcastToOwner("a", []byte("for-a-only"))
	if got, ok := readText(t, wsA, time.Second); !ok || got != "for-a-only" {
		t.Fatalf("A did not receive its message, got %q ok=%v", got, ok)
	}
	if got, ok := readText(t, wsB, 200*time.Millisecond); ok {
		t.Fatalf("B hijacked A's routing via session_init owner field: %q", got)
	}
}

// Test 5 (edge): closing a's audio socket releases only a's session.
func TestAudioWs_DisconnectReleasesOnlyOwnSession(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t, twoUsers, true, fake)

	a := dialPath(t, srv.URL, "/ws/audio", "tok-a")
	b := dialPath(t, srv.URL, "/ws/audio", "tok-b")
	waitUntil(t, "both acquired", func() bool { return len(fake.acquiredList()) == 2 })

	a.Close()
	waitUntil(t, "a released", func() bool { return len(fake.releasedList()) == 1 })
	if got := fake.releasedList(); got[0] != "a" {
		t.Fatalf("released = %v, want [a]", got)
	}

	if err := b.WriteMessage(websocket.BinaryMessage, []byte("B-after")); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "b still forwarding", func() bool { return len(fake.framesFor("b")) == 1 })
	if got := fake.releasedList(); len(got) != 1 {
		t.Fatalf("b was released by a's disconnect: %v", got)
	}
}

// Cap: when the manager refuses a new session the socket is closed with
// 1013 (try again later) and no frames are forwarded for that owner.
func TestAudioWs_SessionCapClosesWith1013(t *testing.T) {
	fake := newOwnerAudio()
	fake.acquireErr = audio.ErrTooManySessions
	srv, _ := startIsolationServer(t, twoUsers, true, fake)

	c := dialPath(t, srv.URL, "/ws/audio", "tok-b")
	c.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, _, err := c.ReadMessage()
	ce, ok := err.(*websocket.CloseError)
	if !ok || ce.Code != websocket.CloseTryAgainLater {
		t.Fatalf("expected close 1013, got %v", err)
	}
	if got := fake.framesFor("b"); len(got) != 0 {
		t.Fatalf("frames forwarded despite refused session: %d", len(got))
	}
	if got := fake.releasedList(); len(got) != 0 {
		t.Fatalf("Release called for a session that was never acquired: %v", got)
	}
}

// Auth disabled (local dev): every client shares the empty owner, so audio
// and transcripts behave exactly as the single-user default.
func TestAudioWs_AuthDisabledUsesEmptyOwner(t *testing.T) {
	fake := newOwnerAudio()
	srv, hub := startIsolationServer(t, nil, false, fake)

	ws := dialPath(t, srv.URL, "/ws", "")
	au := dialPath(t, srv.URL, "/ws/audio", "")
	waitForClients(t, hub, 1)
	if err := au.WriteMessage(websocket.BinaryMessage, []byte("x")); err != nil {
		t.Fatal(err)
	}
	waitUntil(t, "frame forwarded under empty owner", func() bool { return len(fake.framesFor("")) == 1 })

	hub.BroadcastToOwner("", []byte("local"))
	if got, ok := readText(t, ws, time.Second); !ok || got != "local" {
		t.Fatalf("local client did not receive owner-\"\" transcript, got %q ok=%v", got, ok)
	}
}

// AUDIO_ENABLED=false: no controller is wired. The socket must stay open and
// silently drop frames (the documented behaviour) rather than closing, which
// would send the browser into its reconnect loop.
func TestAudioWs_NoControllerKeepsSocketOpenAndDropsFrames(t *testing.T) {
	hub := NewHub()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ServeAudioWs(hub, nil, false, testOrigins, w, r)
	}))
	t.Cleanup(srv.Close)

	c := dialPath(t, srv.URL, "", "")
	for i := 0; i < 3; i++ {
		if err := c.WriteMessage(websocket.BinaryMessage, []byte{1, 2}); err != nil {
			t.Fatalf("write %d failed, socket closed: %v", i, err)
		}
		time.Sleep(20 * time.Millisecond)
	}
	c.SetReadDeadline(time.Now().Add(150 * time.Millisecond))
	if _, _, err := c.ReadMessage(); err != nil {
		if _, closed := err.(*websocket.CloseError); closed {
			t.Fatalf("socket was closed with no controller: %v", err)
		}
	}
}

// P2-A: the frame size cap must apply before any read, including the
// no-controller path, so an oversized frame closes the socket instead of
// being buffered server-side.
func TestAudioWs_NoControllerStillEnforcesFrameSizeLimit(t *testing.T) {
	hub := NewHub()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ServeAudioWs(hub, nil, false, testOrigins, w, r)
	}))
	t.Cleanup(srv.Close)

	c := dialPath(t, srv.URL, "", "")
	big := make([]byte, maxAudioFrameSize+1)
	_ = c.WriteMessage(websocket.BinaryMessage, big)
	c.SetReadDeadline(time.Now().Add(2 * time.Second))
	if _, _, err := c.ReadMessage(); err == nil {
		t.Fatal("oversized frame was accepted on the no-controller path")
	}
}

// P2-B: a silent (half-open) audio socket must be reaped by a read deadline
// so its session ref is released; otherwise dead peers pin sessions forever
// and the cap turns into a lockout.
func TestAudioWs_SilentConnectionIsReapedAndReleased(t *testing.T) {
	// The short wait is injected into this test's own handler only; no
	// package state is mutated, so handlers from other tests are unaffected.
	const shortWait = 300 * time.Millisecond
	fake := newOwnerAudio()
	hub := NewHub()
	hub.SetAudio(fake)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		serveAudioWs(hub, twoUsers, true, testOrigins, shortWait, w, r)
	}))
	t.Cleanup(srv.Close)

	c := dialPath(t, srv.URL, "", "tok-a")
	// Never send anything; also never answer pings (no read loop on the client).
	_ = c
	waitUntil(t, "silent session released", func() bool { return len(fake.releasedList()) == 1 })
}

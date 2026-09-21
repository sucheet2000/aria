package server

import (
	"testing"
)

// Workstream A at the edge: the mute a connection takes belongs to THAT
// connection. These drive real WebSockets so the connection identity is the
// real one the hub assigns, not a string a test made up.

// 7 — an idle tab reconnecting (or simply finishing) must not un-gate a
// sibling that is still speaking. Before this change the second tab's
// tts_unmute cleared the account's single flag and the sibling's microphone
// carried ARIA's voice into Whisper.
func TestWs_IdleTabCannotClearASpeakingSiblingsHold(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t, ownerVerifier{"tok-a": "user_a"}, true, fake)

	speaking := dialPath(t, srv.URL, "/ws", "tok-a")
	idle := dialPath(t, srv.URL, "/ws", "tok-a")

	if err := speaking.WriteJSON(map[string]string{"type": "tts_mute"}); err != nil {
		t.Fatalf("write tts_mute: %v", err)
	}
	waitUntil(t, "owner muted", func() bool {
		muted, ok := fake.mutedFor("user_a")
		return ok && muted
	})

	// The idle tab reconnects and states that it holds nothing.
	if err := idle.WriteJSON(map[string]string{"type": "tts_unmute"}); err != nil {
		t.Fatalf("write tts_unmute: %v", err)
	}
	waitUntil(t, "idle tab processed", func() bool { return fake.holderCount("user_a") >= 1 })

	if muted, ok := fake.mutedFor("user_a"); !ok || !muted {
		t.Fatalf("idle tab cleared the speaking tab's hold (muted=%v ok=%v)", muted, ok)
	}
	if n := fake.holderCount("user_a"); n != 1 {
		t.Fatalf("holders = %d, want 1 (only the speaking tab)", n)
	}
}

// 5/6 — a disconnect drops that connection's hold and no other.
func TestWs_DisconnectDropsOnlyItsOwnHold(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t, ownerVerifier{"tok-a": "user_a"}, true, fake)

	first := dialPath(t, srv.URL, "/ws", "tok-a")
	second := dialPath(t, srv.URL, "/ws", "tok-a")

	for _, c := range []interface{ WriteJSON(any) error }{first, second} {
		if err := c.WriteJSON(map[string]string{"type": "tts_mute"}); err != nil {
			t.Fatalf("write tts_mute: %v", err)
		}
	}
	waitUntil(t, "both tabs holding", func() bool { return fake.holderCount("user_a") == 2 })

	first.Close()

	waitUntil(t, "first hold released", func() bool { return fake.holderCount("user_a") == 1 })
	if muted, ok := fake.mutedFor("user_a"); !ok || !muted {
		t.Fatalf("the surviving tab's hold was dropped too (muted=%v)", muted)
	}
}

// 8 — holds never cross owners.
func TestWs_MuteHoldsAreOwnerScoped(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t,
		ownerVerifier{"tok-a": "user_a", "tok-b": "user_b"}, true, fake)

	a := dialPath(t, srv.URL, "/ws", "tok-a")
	dialPath(t, srv.URL, "/ws", "tok-b")

	if err := a.WriteJSON(map[string]string{"type": "tts_mute"}); err != nil {
		t.Fatalf("write: %v", err)
	}
	waitUntil(t, "A muted", func() bool {
		muted, ok := fake.mutedFor("user_a")
		return ok && muted
	})

	if muted, ok := fake.mutedFor("user_b"); ok && muted {
		t.Fatal("owner B was muted by owner A's hold")
	}
	if n := fake.holderCount("user_b"); n != 0 {
		t.Fatalf("owner B has %d holders, want 0", n)
	}
}

// A client cannot claim to be another connection: the holder is the hub's own
// id for the socket, never anything in the payload.
func TestWs_HolderIdentityIsNotClientSupplied(t *testing.T) {
	fake := newOwnerAudio()
	srv, _ := startIsolationServer(t, ownerVerifier{"tok-a": "user_a"}, true, fake)

	speaking := dialPath(t, srv.URL, "/ws", "tok-a")
	attacker := dialPath(t, srv.URL, "/ws", "tok-a")

	if err := speaking.WriteJSON(map[string]string{"type": "tts_mute"}); err != nil {
		t.Fatalf("write: %v", err)
	}
	waitUntil(t, "muted", func() bool {
		muted, ok := fake.mutedFor("user_a")
		return ok && muted
	})

	// Every holder-like field the attacker can imagine.
	if err := attacker.WriteJSON(map[string]string{
		"type": "tts_unmute", "holder": "1", "id": "1", "client_id": "1", "owner": "user_a",
	}); err != nil {
		t.Fatalf("write: %v", err)
	}
	waitUntil(t, "attacker processed", func() bool { return fake.holderCount("user_a") >= 1 })

	if muted, ok := fake.mutedFor("user_a"); !ok || !muted {
		t.Fatal("a payload field let one connection release another's hold")
	}
}

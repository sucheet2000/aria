package audio

import (
	"slices"
	"testing"
	"time"
)

// V3 — the retained mute must fail CLOSED, not open.
//
// The mute rides the main /ws; the microphone rides /ws/audio. They are
// independent sockets. If the main one blips while the page is alive and ARIA
// is still talking, clearing the mute would put ARIA's own voice straight into
// Whisper — the defect V3 exists to close. So a disconnect must NOT clear it.
//
// The opposite failure has to be bounded too: a tab closed mid-sentence never
// sends tts_unmute, and a mute retained forever would leave that owner's
// microphone dead. The TTL bounds it — far longer than any real utterance, so
// speech is never cut short, and short enough that an abandoned mute heals.

// A brief blip: the entry is fresh, so the rebuilt session stays muted.
func TestSessionManager_FreshRetainedMuteSurvivesAReconnect(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tab", true)
	m.Release("a")
	acquire(t, m, "a")
	writeLine(t, m, "a", "aria-hearing-itself")

	m.SetMuted("a", "tab", false)
	writeLine(t, m, "a", "user-again")

	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "aria-hearing-itself") {
		t.Fatalf("a fresh retained mute was dropped on reconnect: %v", got)
	}
	if !slices.Contains(got, "user-again") {
		t.Fatalf("capture did not return after unmute: %v", got)
	}
}

// A departure: the client never comes back to send tts_unmute, so the mute
// must age out rather than deafen that owner for the life of the process.
func TestSessionManager_RetainedMuteExpiresAfterTTL(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tab", true)
	m.Release("a")
	m.ageMuteHolder("a", "tab", mutedOwnerTTL+time.Second)

	acquire(t, m, "a")
	writeLine(t, m, "a", "user-after-the-tab-came-back")

	got := rec.waitFor(t, "a", 1)
	if !slices.Contains(got, "user-after-the-tab-came-back") {
		t.Fatalf("microphone stayed dead after the retained mute should have expired: %v", got)
	}
	if m.isMutedOwner("a") {
		t.Fatal("the expired entry was not dropped")
	}
}

// Releasing a session sweeps stale entries, so an owner who never returns does
// not sit in the map indefinitely.
func TestSessionManager_ReleaseSweepsStaleRetainedMutes(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "gone")
	m.SetMuted("gone", "tab", true)
	m.ageMuteHolder("gone", "tab", mutedOwnerTTL+time.Second)

	acquire(t, m, "here")
	m.SetMuted("here", "tab", true)

	m.Release("here") // any release is a sweep point

	if m.isMutedOwner("gone") {
		t.Fatal("stale retained mute survived the sweep")
	}
	if !m.isMutedOwner("here") {
		t.Fatal("a fresh retained mute was swept away")
	}
	if n := m.mutedOwnerCount(); n != 1 {
		t.Fatalf("muted owners after sweep = %d, want 1", n)
	}
	m.SetMuted("here", "tab", false)
}

// Two of an owner's connections can call SetMuted concurrently, each from its
// own readPump goroutine. If the map were updated under the lock but the
// worker flag set outside it, the two could land in opposite orders and leave
// the record and the flag disagreeing — either ARIA's voice reaching Whisper
// while the record says muted, or a mute the reconnect logic can no longer
// repair. At rest they must always agree.
func TestSessionManager_ConcurrentSetMutedLeavesFlagAndRecordAgreeing(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	for round := 0; round < 200; round++ {
		done := make(chan struct{}, 2)
		go func() { m.SetMuted("a", "tab", true); done <- struct{}{} }()
		go func() { m.SetMuted("a", "tab", false); done <- struct{}{} }()
		<-done
		<-done

		m.mu.Lock()
		_, recorded := m.mutedOwners["a"]
		s := m.sessions["a"]
		flag := s.worker.muted.Load()
		m.mu.Unlock()

		if recorded != flag {
			t.Fatalf("round %d: retained record says muted=%v but the worker flag is %v",
				round, recorded, flag)
		}
	}
}

// A retained mute applied at Acquire is never re-evaluated while that session
// stays up: the TTL is consulted when a session is created and swept when one
// is released, and neither happens to a session that simply keeps running.
//
// That is deliberate, and it is why the browser re-states its duplex intent
// every time the main socket comes up (ttsResyncRef / resyncTtsMuteState). The
// server does not guess whether a page is still speaking; the page says so. A
// page that has gone away is replaced by a fresh one which owes nothing and
// therefore sends tts_unmute, and that is what heals a live session.
//
// This test pins both halves: the mute persists on its own, and an explicit
// unmute — the one the resync sends — restores capture immediately.
func TestSessionManager_LiveSessionIsHealedByAnExplicitUnmute(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	m.SetMuted("a", "tab", true)
	m.Release("a")

	acquire(t, m, "a") // the reload, inside the TTL: comes up muted, correctly
	writeLine(t, m, "a", "should-still-be-suppressed")

	// Age it past the TTL to show that time alone does not free a live session.
	m.ageMuteHolder("a", "tab", 10*mutedOwnerTTL)
	writeLine(t, m, "a", "still-suppressed-despite-the-ttl")

	// The fresh page comes up, holds nothing, and says so.
	m.SetMuted("a", "tab", false)
	writeLine(t, m, "a", "user-speaking-again")

	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "should-still-be-suppressed") ||
		slices.Contains(got, "still-suppressed-despite-the-ttl") {
		t.Fatalf("audio leaked while the retained mute was in force: %v", got)
	}
	if !slices.Contains(got, "user-speaking-again") {
		t.Fatalf("the resync unmute did not restore capture: %v", got)
	}
}

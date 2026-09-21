package audio

import (
	"slices"
	"testing"
)

// V3 — the browser sends tts_mute once, when ARIA starts speaking, and
// tts_unmute once when it stops. If the owner's /ws/audio socket blips in
// between, the edge rebuilds that owner's session. A fresh worker that started
// unmuted would forward the microphone into Whisper while ARIA is still
// talking, which is exactly the self-trigger V3 exists to prevent.
//
// Each test writes a sentinel line AFTER unmuting and waits for it, so the
// suppressed line has provably had its chance to arrive before we assert.
func TestSessionManager_MuteSurvivesSessionChurnMidSpeech(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", true) // ARIA starts speaking
	writeLine(t, m, "a", "suppressed-while-speaking")

	// The audio socket drops and reconnects while ARIA is still speaking.
	m.Release("a")
	acquire(t, m, "a")
	writeLine(t, m, "a", "aria-hearing-itself")

	m.SetMuted("a", false) // ARIA stops speaking
	writeLine(t, m, "a", "user-again")

	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "aria-hearing-itself") {
		t.Fatalf("mute was lost across session churn: %v reached the pipeline while ARIA spoke", got)
	}
	if !slices.Contains(got, "user-again") {
		t.Fatalf("capture did not come back after unmute: %v", got)
	}
}

// A mute that arrives before the owner has an audio session must still apply
// when that session appears, for the same reason.
func TestSessionManager_MuteBeforeAcquireApplies(t *testing.T) {
	m, rec := newTestManager(t, 8)

	m.SetMuted("a", true)
	acquire(t, m, "a")
	writeLine(t, m, "a", "should-not-reach-whisper")

	m.SetMuted("a", false)
	writeLine(t, m, "a", "live-again")

	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "should-not-reach-whisper") {
		t.Fatalf("mute taken before the session existed was ignored: %v", got)
	}
	if !slices.Contains(got, "live-again") {
		t.Fatalf("capture did not come back: %v", got)
	}
}

// Unmuting must not retain per-owner state, so the muted set cannot grow
// without bound as owners come and go.
func TestSessionManager_UnmuteDropsRetainedState(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", true)
	if n := m.mutedOwnerCount(); n != 1 {
		t.Fatalf("muted owners = %d, want 1", n)
	}
	m.SetMuted("a", false)
	if n := m.mutedOwnerCount(); n != 0 {
		t.Fatalf("retained mute state for %d owners after unmute, want 0", n)
	}
}

// One owner speaking must never mute another (S1).
func TestSessionManager_RetainedMuteIsOwnerScoped(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	m.SetMuted("a", true)
	m.Release("a")
	acquire(t, m, "a")

	writeLine(t, m, "b", "B-unaffected")
	got := rec.waitFor(t, "b", 1)
	if got[0] != "B-unaffected" {
		t.Fatalf("owner B disturbed by owner A's mute: %v", got)
	}
	m.SetMuted("a", false)
}

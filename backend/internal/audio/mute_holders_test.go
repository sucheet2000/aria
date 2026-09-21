package audio

import (
	"fmt"
	"slices"
	"sync"
	"testing"
	"time"
)

// Workstream A — the TTS mute must be held per CONNECTION, not per owner.
//
// One owner can have several tabs open, all sharing one audio session. With a
// single owner-level flag the last writer won: a tab that finished speaking, or
// merely reconnected, cleared the mute while a sibling tab was still talking —
// and that sibling's microphone, in the same room, then carried ARIA's own
// voice into Whisper. The browser's local gate (V3.1) protects the tab that is
// speaking; only the server can protect the tabs that are not.

func mutedNow(t *testing.T, m *SessionManager, owner string) bool {
	t.Helper()
	m.mu.Lock()
	defer m.mu.Unlock()
	s, ok := m.sessions[owner]
	if !ok {
		t.Fatalf("owner %q has no session", owner)
	}
	return s.worker.muted.Load()
}

// 1 — the ordinary single-tab case still works.
func TestMuteHolders_SingleHolderMuteAndUnmute(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tab1", true)
	writeLine(t, m, "a", "suppressed")
	if !mutedNow(t, m, "a") {
		t.Fatal("one holder should mute the owner")
	}

	m.SetMuted("a", "tab1", false)
	writeLine(t, m, "a", "audible-again")
	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "suppressed") {
		t.Fatalf("audio leaked while muted: %v", got)
	}
	if !slices.Contains(got, "audible-again") {
		t.Fatalf("capture did not return: %v", got)
	}
}

// 2 — one tab cannot clear another tab's hold.
func TestMuteHolders_SiblingCannotClearASpeakingTabsHold(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tabA", true)  // tab A starts speaking
	m.SetMuted("a", "tabB", false) // idle tab B says it holds nothing

	if !mutedNow(t, m, "a") {
		t.Fatal("tab B cleared tab A's hold")
	}
	writeLine(t, m, "a", "aria-through-tab-B-microphone")

	m.SetMuted("a", "tabA", false)
	writeLine(t, m, "a", "user-again")
	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "aria-through-tab-B-microphone") {
		t.Fatalf("sibling microphone carried ARIA's voice: %v", got)
	}
}

// 3 and 4 — two holders; the mute lifts only when the last one releases.
func TestMuteHolders_LiftsOnlyOnTheLastRelease(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tabA", true)
	m.SetMuted("a", "tabB", true)
	m.SetMuted("a", "tabA", false)

	if !mutedNow(t, m, "a") {
		t.Fatal("mute lifted while tab B was still speaking")
	}

	m.SetMuted("a", "tabB", false)
	if mutedNow(t, m, "a") {
		t.Fatal("mute survived the last release")
	}
}

// 5 and 6 — a disconnect drops only the disconnecting connection's hold.
func TestMuteHolders_DisconnectDropsOnlyItsOwnHold(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tabA", true)
	m.SetMuted("a", "tabB", true)

	m.ReleaseMuteHolder("a", "tabA") // tab A's socket died

	if !mutedNow(t, m, "a") {
		t.Fatal("tab A disconnecting cleared tab B's hold")
	}
	m.ReleaseMuteHolder("a", "tabB")
	if mutedNow(t, m, "a") {
		t.Fatal("mute survived every holder leaving")
	}
}

// 8 — owner A's holders never touch owner B.
func TestMuteHolders_OwnerIsolation(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	m.SetMuted("a", "tab1", true)
	writeLine(t, m, "b", "B-unaffected")

	got := rec.waitFor(t, "b", 1)
	if got[0] != "B-unaffected" {
		t.Fatalf("owner B disturbed by owner A's mute: %v", got)
	}
	if mutedNow(t, m, "b") {
		t.Fatal("owner B was muted by owner A's holder")
	}
}

// 9 — repeated connect/disconnect leaves nothing behind.
func TestMuteHolders_RepeatedChurnLeavesNoHolders(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	for i := 0; i < 25; i++ {
		holder := fmt.Sprintf("tab%d", i)
		m.SetMuted("a", holder, true)
		m.ReleaseMuteHolder("a", holder)
	}
	if n := m.muteHolderCount("a"); n != 0 {
		t.Fatalf("holders left after churn: %d", n)
	}
	if mutedNow(t, m, "a") {
		t.Fatal("owner left muted after churn")
	}
}

// 10 and 11 — concurrent holders, under the race detector.
func TestMuteHolders_ConcurrentHoldersStayConsistent(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		holder := fmt.Sprintf("tab%d", i)
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 50; j++ {
				m.SetMuted("a", holder, true)
				m.SetMuted("a", holder, false)
			}
		}()
	}
	wg.Wait()

	if n := m.muteHolderCount("a"); n != 0 {
		t.Fatalf("holders left after concurrent churn: %d", n)
	}
	if mutedNow(t, m, "a") {
		t.Fatal("owner left muted after every holder released")
	}
}

// 12 — a holder whose connection vanished without notice ages out.
func TestMuteHolders_StaleHolderExpires(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "ghost", true)
	m.ageMuteHolder("a", "ghost", mutedOwnerTTL+time.Second)

	// Any operation that consults the holders prunes the dead one.
	m.SetMuted("a", "live", false)
	if mutedNow(t, m, "a") {
		t.Fatal("a stale holder kept the owner muted forever")
	}
	writeLine(t, m, "a", "user-after-ghost-expired")
	got := rec.waitFor(t, "a", 1)
	if !slices.Contains(got, "user-after-ghost-expired") {
		t.Fatalf("capture never returned: %v", got)
	}
}

// A fresh holder is not pruned alongside a stale one.
func TestMuteHolders_ExpiryKeepsTheLiveHolder(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "ghost", true)
	m.ageMuteHolder("a", "ghost", mutedOwnerTTL+time.Second)
	m.SetMuted("a", "speaking", true)

	if !mutedNow(t, m, "a") {
		t.Fatal("the live holder's mute was dropped with the stale one")
	}
	if n := m.muteHolderCount("a"); n != 1 {
		t.Fatalf("holders = %d, want 1 (stale pruned, live kept)", n)
	}
}

// 15 — the V3.1 guarantee: a rebuilt session comes up muted if anyone holds.
func TestMuteHolders_RebuiltSessionHonoursRemainingHolders(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")

	m.SetMuted("a", "tabA", true)
	m.Release("a")
	acquire(t, m, "a")
	writeLine(t, m, "a", "aria-hearing-itself")

	m.SetMuted("a", "tabA", false)
	writeLine(t, m, "a", "user-again")

	got := rec.waitFor(t, "a", 1)
	if slices.Contains(got, "aria-hearing-itself") {
		t.Fatalf("the rebuilt session came up unmuted: %v", got)
	}
	if !slices.Contains(got, "user-again") {
		t.Fatalf("capture did not return: %v", got)
	}
}

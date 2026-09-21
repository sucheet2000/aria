package audio

import (
	"context"
	"encoding/json"
	"strings"
	"sync"
	"testing"
	"time"
)

// echoScript is a stand-in for audio_worker.py: it reads whole lines from stdin
// and echoes each back as a one-line JSON transcript. Because every session
// gets its own subprocess, a line written for owner A can only ever come back
// on A's stdout — which is exactly what the isolation tests assert.
const echoScript = `while IFS= read -r line; do printf '{"transcript":"%s"}\n' "$line"; done
`

// routerRecorder captures (owner, transcript) pairs delivered by the manager.
type routerRecorder struct {
	mu   sync.Mutex
	recv map[string][]string
}

func newRouterRecorder() *routerRecorder {
	return &routerRecorder{recv: make(map[string][]string)}
}

func (r *routerRecorder) route(owner string, data []byte) {
	var env struct {
		Payload struct {
			Transcript string `json:"transcript"`
		} `json:"payload"`
	}
	_ = json.Unmarshal(data, &env)
	r.mu.Lock()
	// Trim the even-length padding writeLine adds (see its comment).
	r.recv[owner] = append(r.recv[owner], strings.TrimRight(env.Payload.Transcript, " "))
	r.mu.Unlock()
}

func (r *routerRecorder) got(owner string) []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.recv[owner]...)
}

func (r *routerRecorder) waitFor(t *testing.T, owner string, n int) []string {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if got := r.got(owner); len(got) >= n {
			return got
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("owner %q: timed out waiting for %d transcripts, got %v", owner, n, r.got(owner))
	return nil
}

func newTestManager(t *testing.T, maxSessions int) (*SessionManager, *routerRecorder) {
	t.Helper()
	dir, script := writeScript(t, echoScript)
	rec := newRouterRecorder()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	m := NewSessionManager(ctx, "/bin/sh", script, dir, "base", maxSessions, rec.route)
	t.Cleanup(m.Stop)
	return m, rec
}

// acquire registers owner and waits until its subprocess is up, mirroring the
// real edge where PCM only matters once the worker is alive.
func acquire(t *testing.T, m *SessionManager, owner string) {
	t.Helper()
	if err := m.Acquire(owner); err != nil {
		t.Fatalf("acquire %q: %v", owner, err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for !m.Running(owner) {
		if time.Now().After(deadline) {
			t.Fatalf("owner %q worker did not start", owner)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// writeLine feeds one newline-delimited line as this package's stand-in for a
// PCM frame. WriteAudio forwards whole Int16 samples only, so the payload is
// padded to an even number of bytes; routerRecorder trims the padding back off
// so assertions can compare the line verbatim.
func writeLine(t *testing.T, m *SessionManager, owner, line string) {
	t.Helper()
	payload := line
	if (len(payload)+1)%2 != 0 {
		payload += " "
	}
	m.WriteAudio(owner, []byte(payload+"\n"))
}

// Test 1 — transcript isolation: A's audio produces transcripts only for A,
// B's only for B.
func TestSessionManager_TranscriptIsolation(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	writeLine(t, m, "a", "hello from A")
	gotA := rec.waitFor(t, "a", 1)
	if gotA[0] != "hello from A" {
		t.Fatalf("A got %v, want [hello from A]", gotA)
	}
	if leaked := rec.got("b"); len(leaked) != 0 {
		t.Fatalf("B received A's transcript: %v", leaked)
	}

	writeLine(t, m, "b", "hello from B")
	gotB := rec.waitFor(t, "b", 1)
	if gotB[0] != "hello from B" {
		t.Fatalf("B got %v, want [hello from B]", gotB)
	}
	if gotA := rec.got("a"); len(gotA) != 1 {
		t.Fatalf("A received B's transcript: %v", gotA)
	}
}

// Test 2 — interleaved PCM isolation: frames interleaved A,B,A,B reach only
// their own owner's subprocess; there is no combined stream.
func TestSessionManager_InterleavedFramesStaySeparate(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	writeLine(t, m, "a", "A1")
	writeLine(t, m, "b", "B1")
	writeLine(t, m, "a", "A2")
	writeLine(t, m, "b", "B2")

	gotA := rec.waitFor(t, "a", 2)
	gotB := rec.waitFor(t, "b", 2)
	if strings.Join(gotA, ",") != "A1,A2" {
		t.Fatalf("A stream = %v, want [A1 A2]", gotA)
	}
	if strings.Join(gotB, ",") != "B1,B2" {
		t.Fatalf("B stream = %v, want [B1 B2]", gotB)
	}
}

// Test 3 — mute isolation: muting A drops A's frames only; B keeps transcribing.
func TestSessionManager_MuteIsOwnerScoped(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	m.SetMuted("a", "tab", true)
	writeLine(t, m, "a", "muted-A")
	writeLine(t, m, "b", "B-still-live")

	gotB := rec.waitFor(t, "b", 1)
	if gotB[0] != "B-still-live" {
		t.Fatalf("B got %v", gotB)
	}
	if gotA := rec.got("a"); len(gotA) != 0 {
		t.Fatalf("muted A still produced %v", gotA)
	}

	m.SetMuted("a", "tab", false)
	writeLine(t, m, "a", "A-after-unmute")
	gotA := rec.waitFor(t, "a", 1)
	if gotA[0] != "A-after-unmute" {
		t.Fatalf("A after unmute got %v", gotA)
	}
}

// Test 5 — disconnect isolation: releasing A tears down A's worker and leaves
// B fully functional.
func TestSessionManager_ReleaseDoesNotAffectOtherOwner(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	m.Release("a")
	if m.Running("a") {
		t.Fatal("A's worker still running after release")
	}
	if n := m.SessionCount(); n != 1 {
		t.Fatalf("session count = %d, want 1 (only B)", n)
	}

	writeLine(t, m, "b", "B-after-A-left")
	gotB := rec.waitFor(t, "b", 1)
	if gotB[0] != "B-after-A-left" {
		t.Fatalf("B got %v", gotB)
	}
	// A frame for a released owner must not be routed anywhere.
	writeLine(t, m, "a", "ghost")
	time.Sleep(100 * time.Millisecond)
	if gotA := rec.got("a"); len(gotA) != 0 {
		t.Fatalf("released owner A still produced %v", gotA)
	}
}

// Test 6 — lifecycle cleanup: repeated connect/disconnect leaves no session
// registered and no worker running.
func TestSessionManager_RepeatedAcquireReleaseLeavesNothing(t *testing.T) {
	m, _ := newTestManager(t, 8)
	for i := 0; i < 10; i++ {
		if err := m.Acquire("a"); err != nil {
			t.Fatalf("acquire %d: %v", i, err)
		}
		m.Release("a")
	}
	if n := m.SessionCount(); n != 0 {
		t.Fatalf("session count after churn = %d, want 0", n)
	}
	if m.Running("a") {
		t.Fatal("worker for A still running after final release")
	}
}

// Same-owner behaviour: a second connection from the same owner shares that
// owner's worker (refcounted); the worker survives until the last release.
func TestSessionManager_SameOwnerSharesOneWorker(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "a")
	if n := m.SessionCount(); n != 1 {
		t.Fatalf("session count = %d, want 1 for two connections of one owner", n)
	}

	m.Release("a")
	if n := m.SessionCount(); n != 1 {
		t.Fatalf("session count after first release = %d, want 1", n)
	}
	writeLine(t, m, "a", "still-here")
	if got := rec.waitFor(t, "a", 1); got[0] != "still-here" {
		t.Fatalf("A got %v", got)
	}

	m.Release("a")
	if n := m.SessionCount(); n != 0 {
		t.Fatalf("session count after last release = %d, want 0", n)
	}
}

// Cap: creating more distinct-owner sessions than maxSessions is refused, and
// the refusal does not disturb existing sessions.
func TestSessionManager_CapRefusesNewOwner(t *testing.T) {
	m, rec := newTestManager(t, 1)
	acquire(t, m, "a")
	if err := m.Acquire("b"); err != ErrTooManySessions {
		t.Fatalf("second owner err = %v, want ErrTooManySessions", err)
	}
	if n := m.SessionCount(); n != 1 {
		t.Fatalf("session count = %d, want 1", n)
	}
	writeLine(t, m, "a", "A-unaffected")
	if got := rec.waitFor(t, "a", 1); got[0] != "A-unaffected" {
		t.Fatalf("A got %v", got)
	}
}

// Stop terminates every session and refuses new ones.
func TestSessionManager_StopTerminatesAll(t *testing.T) {
	m, _ := newTestManager(t, 8)
	for _, o := range []string{"a", "b", "c"} {
		acquire(t, m, o)
	}
	m.Stop()
	if n := m.SessionCount(); n != 0 {
		t.Fatalf("session count after Stop = %d, want 0", n)
	}
	for _, o := range []string{"a", "b", "c"} {
		if m.Running(o) {
			t.Fatalf("owner %q still running after Stop", o)
		}
	}
	if err := m.Acquire("d"); err == nil {
		t.Fatal("Acquire after Stop must fail")
	}
	if m.Ready() {
		t.Fatal("Ready must be false after Stop")
	}
}

// Writing or muting an owner with no session is a safe no-op.
func TestSessionManager_UnknownOwnerIsNoop(t *testing.T) {
	m, rec := newTestManager(t, 8)
	m.WriteAudio("nobody", []byte("x\n"))
	m.SetMuted("nobody", "tab", true)
	time.Sleep(50 * time.Millisecond)
	if got := rec.got("nobody"); len(got) != 0 {
		t.Fatalf("unknown owner produced %v", got)
	}
}

// slowExitScript echoes lines like echoScript but, on stdin EOF, lingers before
// announcing its exit — modelling a Whisper worker mid-transcription at teardown.
const slowExitScript = `trap '' TERM
printf '{"transcript":"started"}\n'
while IFS= read -r line; do printf '{"transcript":"%s"}\n' "$line"; done
sleep 0.4
printf '{"transcript":"bye"}\n'
`

// P2-C: a same-owner reconnect during teardown must not start a second
// subprocess alongside the draining one. The new process may only start
// after the old one has exited.
func TestSessionManager_ReacquireWaitsForDrainingSession(t *testing.T) {
	dir, script := writeScript(t, slowExitScript)
	rec := newRouterRecorder()
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	m := NewSessionManager(ctx, "/bin/sh", script, dir, "base", 8, rec.route)
	t.Cleanup(m.Stop)

	acquire(t, m, "a")
	rec.waitFor(t, "a", 1) // "started" from the first process

	releaseDone := make(chan struct{})
	go func() {
		m.Release("a")
		close(releaseDone)
	}()
	time.Sleep(50 * time.Millisecond) // let Release enter teardown
	acquire(t, m, "a")
	<-releaseDone

	got := rec.waitFor(t, "a", 3) // started, bye, started
	if strings.Join(got, ",") != "started,bye,started" {
		t.Fatalf("event order = %v, want [started bye started] (second process must start after the first exits)", got)
	}
	if n := m.SessionCount(); n != 1 {
		t.Fatalf("session count = %d, want 1", n)
	}
}

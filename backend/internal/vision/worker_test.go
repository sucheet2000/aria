package vision

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// countingHub counts broadcasts across restarts (one line per subprocess run).
type countingHub struct{ n atomic.Int64 }

func (h *countingHub) Broadcast(_ []byte)       { h.n.Add(1) }
func (h *countingHub) BroadcastScoped(_ []byte) { h.n.Add(1) }

// slowHub records broadcasts without internal synchronisation and sleeps while
// broadcasting, so that -race flags any overlap between two runs' scanner
// goroutines (proving they are joined before run() returns).
type slowHub struct {
	received [][]byte
}

func (h *slowHub) Broadcast(data []byte) { h.record(data) }

func (h *slowHub) BroadcastScoped(data []byte) { h.record(data) }

func (h *slowHub) record(data []byte) {
	time.Sleep(60 * time.Millisecond)
	h.received = append(h.received, data)
}

func writeScript(t *testing.T, body string) (dir, path string) {
	t.Helper()
	dir = t.TempDir()
	path = filepath.Join(dir, "fake.sh")
	if err := os.WriteFile(path, []byte(body), 0o755); err != nil {
		t.Fatalf("write script: %v", err)
	}
	return dir, path
}

func TestNewWorkerUsesWorkDir(t *testing.T) {
	w := New("python3", "vision_worker.py", "/tmp/aria", &slowHub{})
	if w.workDir != "/tmp/aria" {
		t.Errorf("expected workDir '/tmp/aria', got %q", w.workDir)
	}
	if w.pythonBin != "python3" {
		t.Errorf("expected pythonBin 'python3', got %q", w.pythonBin)
	}
	if w.scriptPath != "vision_worker.py" {
		t.Errorf("expected scriptPath 'vision_worker.py', got %q", w.scriptPath)
	}
}

// TestRun_JoinsScannerGoroutines runs the subprocess repeatedly. If run() returns
// before its scanner goroutines finish, the next run's goroutine overlaps with the
// previous one and both call the unsynchronised slowHub concurrently, which -race
// flags.
func TestRun_JoinsScannerGoroutines(t *testing.T) {
	const runs = 8
	dir, script := writeScript(t, "echo '{\"v\":1}'\n")
	hub := &slowHub{}
	w := New("/bin/sh", script, dir, hub)

	for i := 0; i < runs; i++ {
		if err := w.run(context.Background()); err != nil {
			t.Fatalf("run %d returned error: %v", i, err)
		}
	}

	// Each run emits exactly one line; if the scanner goroutine were not joined
	// before run() returns, output would be lost (or double-counted across runs).
	if len(hub.received) != runs {
		t.Fatalf("expected %d broadcasts (one per joined run), got %d", runs, len(hub.received))
	}
}

// TestStart_RestartsOnUnexpectedExit proves the subprocess is relaunched after a
// non-zero exit (a crash) while the context is still live. The buggy loop returned
// on the first cmd.Wait error and never restarted.
func TestStart_RestartsOnUnexpectedExit(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"v\":1}'\nexit 1\n")
	hub := &countingHub{}
	w := New("/bin/sh", script, dir, hub)
	w.restartDelay = time.Millisecond

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(done)
	}()

	deadline := time.After(3 * time.Second)
	for hub.n.Load() < 2 {
		select {
		case <-deadline:
			cancel()
			<-done
			t.Fatalf("expected >=2 subprocess runs (restart), got %d", hub.n.Load())
		case <-time.After(2 * time.Millisecond):
		}
	}
	cancel()
	<-done
}

// TestStart_ConcurrentReentrancy_NoRace hammers Start() from many goroutines. The
// re-entrancy guard reads and writes w.cancel; without a lock these concurrent
// accesses race. With the guard, exactly one loop runs and the rest return nil.
func TestStart_ConcurrentReentrancy_NoRace(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"v\":1}'\nexit 1\n")
	w := New("/bin/sh", script, dir, &countingHub{})
	w.restartDelay = time.Millisecond

	ctx, cancel := context.WithCancel(context.Background())
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_ = w.Start(ctx)
		}()
	}

	time.Sleep(30 * time.Millisecond)
	cancel()
	wg.Wait()
	w.Stop()
}

// waitForProcess polls until run() has published a started subprocess handle and
// returns it. It reads w.cmd under procMu so the read is race-free.
func waitForProcess(t *testing.T, w *Worker) *exec.Cmd {
	t.Helper()
	for i := 0; i < 400; i++ {
		w.procMu.Lock()
		cmd := w.cmd
		w.procMu.Unlock()
		if cmd != nil && cmd.Process != nil {
			return cmd
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("subprocess did not start in time")
	return nil
}

// waitForBroadcast polls until the hub has received at least one broadcast.
func waitForBroadcast(t *testing.T, hub *countingHub) {
	t.Helper()
	for i := 0; i < 400; i++ {
		if hub.n.Load() >= 1 {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("no broadcast observed in time")
}

// TestStop_SingleWaitOwner_EscalatesToSIGKILL proves two things at once under -race:
//   - run() is the SOLE cmd.Wait() owner: while run()'s Wait() is in-flight on a
//     live process, Stop() must NOT call a second cmd.Wait() (a double Wait races
//     on the Cmd's internal ProcessState).
//   - Stop() still escalates to SIGKILL when the process ignores SIGTERM.
//
// The fake script traps (ignores) SIGTERM and stays alive, so only SIGKILL can
// reap it. run() is invoked directly (no Start/cancel) so the exec.CommandContext
// cancellation does not pre-empt Stop()'s own SIGTERM -> timeout -> SIGKILL path.
func TestStop_SingleWaitOwner_EscalatesToSIGKILL(t *testing.T) {
	hub := &countingHub{}
	dir, script := writeScript(t, "trap '' TERM\necho '{\"v\":1}'\nwhile true; do sleep 0.05; done\n")
	w := New("/bin/sh", script, dir, hub)
	w.stopTimeout = 300 * time.Millisecond

	runDone := make(chan struct{})
	go func() {
		_ = w.run(context.Background())
		close(runDone)
	}()

	waitForProcess(t, w)
	// Wait for the script's echo line so we know `trap '' TERM` (which runs first)
	// is installed; otherwise a SIGTERM before the trap would kill the shell and
	// bypass the escalation path we mean to exercise.
	waitForBroadcast(t, hub)

	start := time.Now()
	w.Stop()
	elapsed := time.Since(start)

	if elapsed < w.stopTimeout {
		t.Fatalf("Stop returned in %v; expected >= %v (SIGTERM ignored -> escalation path)", elapsed, w.stopTimeout)
	}

	select {
	case <-runDone:
	case <-time.After(2 * time.Second):
		t.Fatal("run() did not return after Stop; the single Wait() owner never reaped the process")
	}
}

// TestStop_ConcurrentWithRestartLoop_NoRace runs Stop() concurrently with Start()'s
// restart loop. The subprocess exits non-zero so the loop keeps relaunching; Stop()
// must tear everything down with run() remaining the sole cmd.Wait() owner, with no
// data race between the loop's in-flight Wait() and Stop().
func TestStop_ConcurrentWithRestartLoop_NoRace(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"v\":1}'\nexit 1\n")
	w := New("/bin/sh", script, dir, &countingHub{})
	w.restartDelay = 5 * time.Millisecond
	w.stopTimeout = 200 * time.Millisecond

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	startDone := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(startDone)
	}()

	// Let the restart loop cycle a few times before tearing down.
	time.Sleep(40 * time.Millisecond)

	w.Stop()
	cancel()

	select {
	case <-startDone:
	case <-time.After(3 * time.Second):
		t.Fatal("Start did not return after Stop/cancel")
	}
}

// TestStart_CancelledContextReturnsPromptly proves a cancelled context returns nil
// without entering the restart backoff, even with a very long restart delay.
func TestStart_CancelledContextReturnsPromptly(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"v\":1}'\nexit 1\n")
	w := New("/bin/sh", script, dir, &countingHub{})
	w.restartDelay = time.Hour

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	done := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Start did not return promptly on cancelled context")
	}
}

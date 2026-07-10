package audio

import (
	"context"
	"os"
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

// writeScript writes an executable shell script to a temp dir and returns its path.
func writeScript(t *testing.T, body string) (dir, path string) {
	t.Helper()
	dir = t.TempDir()
	path = filepath.Join(dir, "fake.sh")
	if err := os.WriteFile(path, []byte(body), 0o755); err != nil {
		t.Fatalf("write script: %v", err)
	}
	return dir, path
}

// TestMute_ConcurrentWithRestart_NoRace hammers Mute(true/false) while run()
// swaps the stdin pipe between a live pipe and nil across the process lifecycle.
// Without mutex protection the -race detector flags the unsynchronised access.
func TestMute_ConcurrentWithRestart_NoRace(t *testing.T) {
	dir, script := writeScript(t, "sleep 0.2\n")
	w := New("/bin/sh", script, dir, "base", &slowHub{})

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(done)
	}()

	stop := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
					w.Mute(n%2 == 0)
				}
			}
		}(i)
	}

	time.Sleep(300 * time.Millisecond)
	close(stop)
	wg.Wait()

	cancel()
	w.Stop()
	<-done
}

// TestRun_JoinsScannerGoroutines runs the subprocess repeatedly. If run() returns
// before its scanner goroutines finish, the next run's goroutine overlaps with the
// previous one and both call the unsynchronised slowHub concurrently, which -race
// flags.
func TestRun_JoinsScannerGoroutines(t *testing.T) {
	const runs = 8
	dir, script := writeScript(t, "echo '{\"a\":1}'\n")
	hub := &slowHub{}
	w := New("/bin/sh", script, dir, "base", hub)

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
	dir, script := writeScript(t, "echo '{\"a\":1}'\nexit 1\n")
	hub := &countingHub{}
	w := New("/bin/sh", script, dir, "base", hub)
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

// TestStop_DuringRestart_NoRace calls Stop() concurrently while the restart loop
// keeps reassigning w.cmd, proving the process handle is read/written under a lock.
func TestStop_DuringRestart_NoRace(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"a\":1}'\nexit 1\n")
	w := New("/bin/sh", script, dir, "base", &countingHub{})
	w.restartDelay = time.Millisecond

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(done)
	}()

	time.Sleep(20 * time.Millisecond) // let the loop churn so w.cmd is reassigned

	var sg sync.WaitGroup
	for i := 0; i < 4; i++ {
		sg.Add(1)
		go func() {
			defer sg.Done()
			w.Stop()
		}()
	}
	sg.Wait()

	cancel()
	<-done
}

// TestStart_CancelledContextReturnsPromptly proves a cancelled context returns nil
// without entering the restart backoff, even with a very long restart delay.
func TestStart_CancelledContextReturnsPromptly(t *testing.T) {
	dir, script := writeScript(t, "echo '{\"a\":1}'\nexit 1\n")
	w := New("/bin/sh", script, dir, "base", &countingHub{})
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

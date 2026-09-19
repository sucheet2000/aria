package audio

import (
	"bytes"
	"context"
	"sync"
	"testing"
	"time"
)

// recordingPipe is an io.WriteCloser that records everything written to it,
// standing in for the subprocess stdin pipe.
type recordingPipe struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (p *recordingPipe) Write(b []byte) (int, error) {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.buf.Write(b)
}

func (p *recordingPipe) Close() error { return nil }

func (p *recordingPipe) Bytes() []byte {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]byte(nil), p.buf.Bytes()...)
}

func TestWriteAudio_ForwardsPCMToStdin(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	frame := []byte{1, 2, 3, 4, 5, 6}
	w.WriteAudio(frame)

	if got := pipe.Bytes(); !bytes.Equal(got, frame) {
		t.Fatalf("stdin got %v, want %v", got, frame)
	}
}

func TestWriteAudio_DropsFramesWhenMuted(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	w.Mute(true)
	w.WriteAudio([]byte{1, 2, 3, 4})
	if got := pipe.Bytes(); len(got) != 0 {
		t.Fatalf("muted worker forwarded %d bytes, want 0", len(got))
	}

	w.Mute(false)
	w.WriteAudio([]byte{9, 8})
	if got := pipe.Bytes(); !bytes.Equal(got, []byte{9, 8}) {
		t.Fatalf("after unmute stdin got %v, want [9 8]", got)
	}
}

func TestWriteAudio_NoStdinPipe_NoPanic(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	// stdinPipe is nil (no subprocess running); WriteAudio must be a no-op.
	w.WriteAudio([]byte{1, 2, 3})
}

// TestMute_DoesNotWriteToStdin proves the mute path no longer emits JSON to the
// subprocess stdin — stdin now carries raw PCM only, so muting is a Go-edge gate.
func TestMute_DoesNotWriteToStdin(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	w.Mute(true)
	w.Mute(false)

	if got := pipe.Bytes(); len(got) != 0 {
		t.Fatalf("Mute wrote %d bytes to stdin, want 0 (stdin carries PCM only)", len(got))
	}
}

// TestWriteAudio_ConcurrentWithRestart_NoRace hammers WriteAudio and Mute while
// run() swaps the stdin pipe between a live pipe and nil across the process
// lifecycle. Without stdinMu protection the -race detector flags the access.
func TestWriteAudio_ConcurrentWithRestart_NoRace(t *testing.T) {
	dir, script := writeScript(t, "sleep 0.2\n")
	w := New("/bin/sh", script, dir, "base", (&slowHub{}).sink)

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		_ = w.Start(ctx)
		close(done)
	}()

	stop := make(chan struct{})
	var wg sync.WaitGroup
	frame := make([]byte, 960)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			for {
				select {
				case <-stop:
					return
				default:
					w.WriteAudio(frame)
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

package audio

import (
	"testing"
)

// Workstream G — the subprocess reads the stdin stream as a flat sequence of
// little-endian Int16 samples. It has no frame markers: it counts bytes. So a
// single odd-length write shifts the parity of everything after it, and every
// subsequent sample is assembled from the high byte of one and the low byte of
// the next. The audio does not fail loudly, it turns to noise, for the rest of
// the session.

func TestWriteAudio_ForwardsOnlyWholeSamples(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	w.WriteAudio([]byte{0x01, 0x02, 0x03}) // three bytes: one sample and a half

	got := pipe.Bytes()
	if len(got)%2 != 0 {
		t.Fatalf("forwarded %d bytes, which is not a whole number of samples", len(got))
	}
	if len(got) != 2 {
		t.Fatalf("forwarded %d bytes, want the 1 whole sample", len(got))
	}
}

// The parity of the stream must survive a malformed frame: a later well-formed
// frame has to land on the same byte boundary it would have without it.
func TestWriteAudio_OddFrameDoesNotShiftLaterSamples(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	w.WriteAudio([]byte{0xAA, 0xBB, 0xCC})       // malformed: odd
	w.WriteAudio([]byte{0x11, 0x22, 0x33, 0x44}) // well formed

	got := pipe.Bytes()
	if len(got)%2 != 0 {
		t.Fatalf("stream parity broken: %d bytes", len(got))
	}
	// The well-formed frame must appear intact and sample-aligned.
	if len(got) < 4 {
		t.Fatalf("well-formed frame was lost: %v", got)
	}
	tail := got[len(got)-4:]
	want := []byte{0x11, 0x22, 0x33, 0x44}
	for i := range want {
		if tail[i] != want[i] {
			t.Fatalf("well-formed frame was shifted: got %v, want %v", tail, want)
		}
	}
}

// Several malformed frames in a row must not accumulate a drift.
func TestWriteAudio_RepeatedOddFramesStayAligned(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	for i := 0; i < 10; i++ {
		w.WriteAudio([]byte{0x01, 0x02, 0x03, 0x04, 0x05}) // 5 bytes each
	}

	got := pipe.Bytes()
	if len(got)%2 != 0 {
		t.Fatalf("drift after repeated odd frames: %d bytes", len(got))
	}
	if len(got) != 10*4 {
		t.Fatalf("forwarded %d bytes, want %d (4 whole-sample bytes per frame)",
			len(got), 10*4)
	}
}

// A lone byte carries no sample at all and must be dropped entirely.
func TestWriteAudio_SingleByteFrameIsDropped(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	w.WriteAudio([]byte{0x7F})

	if got := pipe.Bytes(); len(got) != 0 {
		t.Fatalf("forwarded %d bytes for a 1-byte frame, want 0", len(got))
	}
}

// Well-formed traffic is untouched: this guard must cost nothing in the
// ordinary case.
func TestWriteAudio_EvenFrameIsForwardedVerbatim(t *testing.T) {
	w := New("python3", "s.py", "/tmp", "base", nopSink)
	pipe := &recordingPipe{}
	w.setStdinPipe(pipe)

	frame := []byte{0x01, 0x02, 0x03, 0x04, 0x05, 0x06}
	w.WriteAudio(frame)

	got := pipe.Bytes()
	if len(got) != len(frame) {
		t.Fatalf("forwarded %d bytes, want %d", len(got), len(frame))
	}
	for i := range frame {
		if got[i] != frame[i] {
			t.Fatalf("byte %d changed: got %#x want %#x", i, got[i], frame[i])
		}
	}
}

// Owner isolation: a malformed frame from one owner must not disturb another.
func TestSessionManager_OddFrameIsOwnerScoped(t *testing.T) {
	m, rec := newTestManager(t, 8)
	acquire(t, m, "a")
	acquire(t, m, "b")

	m.WriteAudio("a", []byte{0x01, 0x02, 0x03}) // malformed, owner a
	writeLine(t, m, "b", "B-unaffected")

	got := rec.waitFor(t, "b", 1)
	if got[0] != "B-unaffected" {
		t.Fatalf("owner B disturbed by owner A's malformed frame: %v", got)
	}
}

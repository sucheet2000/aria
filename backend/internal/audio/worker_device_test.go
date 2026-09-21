package audio

import (
	"strings"
	"testing"
)

// The whisper-device commit added validation and a fallback inside the Python
// transcriber, but nothing in production could select a device: the worker was
// spawned with --model only, so the setting was reachable from tests alone.
// These pin the wiring end to end at the Go edge.

func TestWorker_PassesTheConfiguredDeviceToTheSubprocess(t *testing.T) {
	for _, device := range []string{"cpu", "auto", "cuda"} {
		t.Run(device, func(t *testing.T) {
			w := New("python3", "audio_worker.py", "/tmp", "base", device, nopSink)
			if w.whisperDevice != device {
				t.Fatalf("worker kept device %q, want %q", w.whisperDevice, device)
			}
		})
	}
}

func TestSessionManager_HandsTheDeviceToEachWorker(t *testing.T) {
	m, _ := newTestManager(t, 8)
	acquire(t, m, "a")

	m.mu.Lock()
	s := m.sessions["a"]
	m.mu.Unlock()

	if s.worker.whisperDevice != "cpu" {
		t.Fatalf("worker device = %q, want the manager's configured value", s.worker.whisperDevice)
	}
}

// The argv the subprocess actually receives. A missing flag here is exactly how
// the setting came to be unreachable in the first place.
func TestWorker_ArgvCarriesModelAndDevice(t *testing.T) {
	w := New("python3", "/tmp/audio_worker.py", "/tmp", "small", "auto", nopSink)
	argv := w.subprocessArgs()

	joined := strings.Join(argv, " ")
	for _, want := range []string{"--model small", "--device auto"} {
		if !strings.Contains(joined, want) {
			t.Fatalf("argv %q does not carry %q", joined, want)
		}
	}
}

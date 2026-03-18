package audio

import "testing"

type mockHub struct{}

func (m *mockHub) Broadcast(_ []byte) {}

func TestNewWorkerFields(t *testing.T) {
	hub := &mockHub{}
	w := New("python3", "audio_worker.py", "/tmp", "base", hub)

	if w.pythonBin != "python3" {
		t.Errorf("expected pythonBin 'python3', got %q", w.pythonBin)
	}
	if w.scriptPath != "audio_worker.py" {
		t.Errorf("expected scriptPath 'audio_worker.py', got %q", w.scriptPath)
	}
	if w.workDir != "/tmp" {
		t.Errorf("expected workDir '/tmp', got %q", w.workDir)
	}
	if w.whisperModel != "base" {
		t.Errorf("expected whisperModel 'base', got %q", w.whisperModel)
	}
	if w.hub != hub {
		t.Error("expected hub to match provided hub")
	}
}

func TestNewWorkerNotNil(t *testing.T) {
	w := New("python3", "script.py", "/tmp", "small", &mockHub{})
	if w == nil {
		t.Fatal("expected non-nil Worker")
	}
}

func TestStopNoopWhenNotStarted(t *testing.T) {
	w := New("python3", "script.py", "/tmp", "base", &mockHub{})
	// Stop should not panic when cmd is nil
	w.Stop()
}

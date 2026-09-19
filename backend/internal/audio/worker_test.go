package audio

import "testing"

func nopSink(_ []byte) {}

func TestNewWorkerFields(t *testing.T) {
	w := New("python3", "audio_worker.py", "/tmp", "base", nopSink)

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
	if w.sink == nil {
		t.Error("expected sink to be set")
	}
}

func TestNewWorkerNotNil(t *testing.T) {
	w := New("python3", "script.py", "/tmp", "small", nopSink)
	if w == nil {
		t.Fatal("expected non-nil Worker")
	}
}

func TestStopNoopWhenNotStarted(t *testing.T) {
	w := New("python3", "script.py", "/tmp", "base", nopSink)
	// Stop should not panic when cmd is nil
	w.Stop()
}

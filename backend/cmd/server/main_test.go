package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/sucheet2000/aria/backend/internal/config"
)

// WHISPER_DEVICE once reached config.Load and was never assigned, while every
// test on either side of that gap passed. The same shape exists one hop later:
// main hands NewSessionManager five positional strings, so swapping the model
// and the device (or passing "") compiles and passed the whole suite.
//
// This builds the manager exactly as main does and runs a real worker process:
// /bin/sh stands in for python and records the argv it was given, which is the
// only place the config's values are observable.
func TestNewAudioSessions_ConfigReachesTheWorkerArgv(t *testing.T) {
	dir := t.TempDir()
	argvFile := filepath.Join(dir, "argv")
	script := filepath.Join(dir, "fake_audio_worker.sh")
	// Record argv, then keep reading stdin until the manager closes it.
	body := "printf '%s\\n' \"$@\" > \"$ARIA_TEST_ARGV_OUT\"\ncat > /dev/null\n"
	if err := os.WriteFile(script, []byte(body), 0o755); err != nil {
		t.Fatalf("write fake worker: %v", err)
	}
	t.Setenv("ARIA_TEST_ARGV_OUT", argvFile)

	cfg := &config.Config{
		PythonBin:        "/bin/sh",
		AudioScript:      script,
		WhisperModel:     "model-from-config",
		WhisperDevice:    "device-from-config",
		AudioMaxSessions: 1,
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	sessions := newAudioSessions(ctx, cfg, dir, func(string, []byte) {})
	t.Cleanup(sessions.Stop)

	if err := sessions.Acquire("owner-1"); err != nil {
		t.Fatalf("acquire: %v", err)
	}
	defer sessions.Release("owner-1")

	var got []string
	deadline := time.Now().Add(10 * time.Second)
	for {
		if raw, err := os.ReadFile(argvFile); err == nil && strings.Count(string(raw), "\n") >= 4 {
			got = strings.Split(strings.TrimRight(string(raw), "\n"), "\n")
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the worker process never started, or never received its argv")
		}
		time.Sleep(20 * time.Millisecond)
	}

	want := []string{"--model", "model-from-config", "--device", "device-from-config"}
	if strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("worker argv (after the script) = %q, want %q", got, want)
	}
}

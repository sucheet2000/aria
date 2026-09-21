package config

import (
	"os"
	"testing"
)

// The device setting is read from the environment in one place and consumed in
// another; this asserts the value actually survives the journey. It did not:
// Load() parsed WHISPER_DEVICE into a local and then built the Config without
// assigning it, so cfg.WhisperDevice was always "" and the worker was spawned
// with --device "". Both ends of that chain had tests — the Go side proved the
// argv carried a --device flag, the Python side proved a device reaching the
// transcriber was honoured — and neither looked at the wire between them.
func TestLoad_WhisperDeviceReachesTheConfig(t *testing.T) {
	t.Setenv("WHISPER_DEVICE", "cuda")

	cfg := Load()

	if cfg.WhisperDevice != "cuda" {
		t.Fatalf("WhisperDevice = %q, want %q — the env value never reached the struct",
			cfg.WhisperDevice, "cuda")
	}
}

func TestLoad_WhisperDeviceDefaultsToCPU(t *testing.T) {
	os.Unsetenv("WHISPER_DEVICE")

	if got := Load().WhisperDevice; got != "cpu" {
		t.Fatalf("WhisperDevice = %q, want the documented default %q", got, "cpu")
	}
}

// The same shape as the test above, for the same reason. The metrics scrape
// credential is read here and consumed in internal/server; every metrics test
// builds a Config by hand, so the handler's behaviour was proven against a
// token the loader was never proven to supply. Deleting the assignment left
// the whole suite green — and an empty token makes metricsAuthorized return
// true for everyone.
func TestLoad_MetricsTokenReachesTheConfig(t *testing.T) {
	t.Setenv("METRICS_TOKEN", "scrape-secret-value")

	if got := Load().MetricsToken; got != "scrape-secret-value" {
		t.Fatalf("MetricsToken = %q, want %q — the env value never reached the struct",
			got, "scrape-secret-value")
	}
}

func TestLoad_MetricsTokenDefaultsToEmpty(t *testing.T) {
	os.Unsetenv("METRICS_TOKEN")

	if got := Load().MetricsToken; got != "" {
		t.Fatalf("MetricsToken = %q, want empty when unset", got)
	}
}

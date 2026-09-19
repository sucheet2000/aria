package config

import (
	"reflect"
	"testing"
)

func TestLoad_ClerkSettings(t *testing.T) {
	t.Setenv("CLERK_SECRET_KEY", "sk_test_123")
	t.Setenv("CLERK_JWT_ISSUER", "https://clerk.example.com")

	cfg := Load()

	if cfg.ClerkSecretKey != "sk_test_123" {
		t.Errorf("ClerkSecretKey = %q, want sk_test_123", cfg.ClerkSecretKey)
	}
	if cfg.ClerkJWTIssuer != "https://clerk.example.com" {
		t.Errorf("ClerkJWTIssuer = %q, want https://clerk.example.com", cfg.ClerkJWTIssuer)
	}
}

func TestLoad_HostDefaultsToLoopback(t *testing.T) {
	t.Setenv("HOST", "")

	cfg := Load()

	if cfg.Host != "127.0.0.1" {
		t.Errorf("Host = %q, want 127.0.0.1", cfg.Host)
	}
}

func TestLoad_PythonBaseURLDefault(t *testing.T) {
	t.Setenv("PYTHON_BASE_URL", "")

	cfg := Load()

	if cfg.PythonBaseURL != "http://127.0.0.1:8000" {
		t.Errorf("PythonBaseURL = %q, want http://127.0.0.1:8000", cfg.PythonBaseURL)
	}
}

func TestLoad_PythonBaseURLEnvOverride(t *testing.T) {
	t.Setenv("PYTHON_BASE_URL", "http://python.internal:9000")

	cfg := Load()

	if cfg.PythonBaseURL != "http://python.internal:9000" {
		t.Errorf("PythonBaseURL = %q, want http://python.internal:9000", cfg.PythonBaseURL)
	}
}

func TestLoad_ClerkSettingsDefaultEmpty(t *testing.T) {
	t.Setenv("CLERK_SECRET_KEY", "")
	t.Setenv("CLERK_JWT_ISSUER", "")

	cfg := Load()

	if cfg.ClerkSecretKey != "" {
		t.Errorf("ClerkSecretKey = %q, want empty", cfg.ClerkSecretKey)
	}
	if cfg.ClerkJWTIssuer != "" {
		t.Errorf("ClerkJWTIssuer = %q, want empty", cfg.ClerkJWTIssuer)
	}
}

func TestLoad_AllowedOriginsDefault(t *testing.T) {
	t.Setenv("ALLOWED_ORIGINS", "")
	cfg := Load()
	want := []string{"http://localhost:3000", "http://127.0.0.1:3000"}
	if !reflect.DeepEqual(cfg.AllowedOrigins, want) {
		t.Errorf("AllowedOrigins = %v, want %v", cfg.AllowedOrigins, want)
	}
}

func TestLoad_AllowedOriginsEnvOverride(t *testing.T) {
	t.Setenv("ALLOWED_ORIGINS", "https://app.aria.ai , http://localhost:3000 ")

	cfg := Load()

	want := []string{"https://app.aria.ai", "http://localhost:3000"}
	if len(cfg.AllowedOrigins) != len(want) {
		t.Fatalf("AllowedOrigins = %v, want %v", cfg.AllowedOrigins, want)
	}
	for i, w := range want {
		if cfg.AllowedOrigins[i] != w {
			t.Errorf("AllowedOrigins[%d] = %q, want %q", i, cfg.AllowedOrigins[i], w)
		}
	}
}

func TestLoad_AllowedOriginsFromEnv(t *testing.T) {
	t.Setenv("ALLOWED_ORIGINS", "https://a.com, https://b.com ,https://c.com")
	cfg := Load()
	want := []string{"https://a.com", "https://b.com", "https://c.com"}
	if !reflect.DeepEqual(cfg.AllowedOrigins, want) {
		t.Errorf("AllowedOrigins = %v, want %v", cfg.AllowedOrigins, want)
	}
}

func TestLoad_RateLimitDefaults(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "")
	t.Setenv("RATE_LIMIT_BURST", "")
	t.Setenv("RATE_LIMIT_GLOBAL_RPS", "")
	t.Setenv("RATE_LIMIT_GLOBAL_BURST", "")
	cfg := Load()
	if cfg.RateLimitRPS != 5 {
		t.Errorf("RateLimitRPS = %v, want 5", cfg.RateLimitRPS)
	}
	if cfg.RateLimitBurst != 10 {
		t.Errorf("RateLimitBurst = %v, want 10", cfg.RateLimitBurst)
	}
	if cfg.RateLimitGlobalRPS != 50 {
		t.Errorf("RateLimitGlobalRPS = %v, want 50", cfg.RateLimitGlobalRPS)
	}
	if cfg.RateLimitGlobalBurst != 100 {
		t.Errorf("RateLimitGlobalBurst = %v, want 100", cfg.RateLimitGlobalBurst)
	}
}

func TestLoad_RateLimitFromEnv(t *testing.T) {
	t.Setenv("RATE_LIMIT_RPS", "2.5")
	t.Setenv("RATE_LIMIT_BURST", "7")
	t.Setenv("RATE_LIMIT_GLOBAL_RPS", "40")
	t.Setenv("RATE_LIMIT_GLOBAL_BURST", "80")
	cfg := Load()
	if cfg.RateLimitRPS != 2.5 {
		t.Errorf("RateLimitRPS = %v, want 2.5", cfg.RateLimitRPS)
	}
	if cfg.RateLimitBurst != 7 {
		t.Errorf("RateLimitBurst = %v, want 7", cfg.RateLimitBurst)
	}
	if cfg.RateLimitGlobalRPS != 40 {
		t.Errorf("RateLimitGlobalRPS = %v, want 40", cfg.RateLimitGlobalRPS)
	}
	if cfg.RateLimitGlobalBurst != 80 {
		t.Errorf("RateLimitGlobalBurst = %v, want 80", cfg.RateLimitGlobalBurst)
	}
}

func TestLoad_AudioMaxSessionsDefault(t *testing.T) {
	t.Setenv("AUDIO_MAX_SESSIONS", "")
	cfg := Load()
	if cfg.AudioMaxSessions != 8 {
		t.Fatalf("AudioMaxSessions = %d, want default 8", cfg.AudioMaxSessions)
	}
}

func TestLoad_AudioMaxSessionsEnvOverride(t *testing.T) {
	t.Setenv("AUDIO_MAX_SESSIONS", "3")
	cfg := Load()
	if cfg.AudioMaxSessions != 3 {
		t.Fatalf("AudioMaxSessions = %d, want 3", cfg.AudioMaxSessions)
	}
}

func TestLoad_AudioMaxSessionsClampsToAtLeastOne(t *testing.T) {
	t.Setenv("AUDIO_MAX_SESSIONS", "0")
	if cfg := Load(); cfg.AudioMaxSessions != 1 {
		t.Fatalf("AudioMaxSessions = %d, want clamp to 1", cfg.AudioMaxSessions)
	}
	t.Setenv("AUDIO_MAX_SESSIONS", "-5")
	if cfg := Load(); cfg.AudioMaxSessions != 1 {
		t.Fatalf("AudioMaxSessions = %d, want clamp to 1", cfg.AudioMaxSessions)
	}
}

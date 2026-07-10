package config

import "testing"

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
	if len(cfg.AllowedOrigins) != len(want) {
		t.Fatalf("AllowedOrigins = %v, want %v", cfg.AllowedOrigins, want)
	}
	for i, w := range want {
		if cfg.AllowedOrigins[i] != w {
			t.Errorf("AllowedOrigins[%d] = %q, want %q", i, cfg.AllowedOrigins[i], w)
		}
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

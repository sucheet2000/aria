package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

// defaultAllowedOrigins is the CORS allow-list used when ALLOWED_ORIGINS is unset.
var defaultAllowedOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

// Config holds all runtime configuration for the server.
type Config struct {
	Host          string
	Port          int
	PythonBin     string
	AnthropicKey  string
	ElevenLabsKey string
	Debug         bool
	AudioScript   string
	AudioEnabled  bool
	// AudioMaxSessions caps concurrent per-owner audio workers (each loads its
	// own Whisper model). Clamped to >= 1 so the cap can never be disabled.
	AudioMaxSessions  int
	TTSProvider       string
	ElevenLabsVoiceID string
	WhisperModel      string
	WhisperDevice     string
	ClerkSecretKey    string
	ClerkJWTIssuer    string
	// InternalAuthSecret is the shared secret Go sends (X-Internal-Auth) and
	// Python requires. Empty disables the boundary for local dev.
	InternalAuthSecret string

	// MetricsToken is the dedicated scrape credential for GET /metrics. It is
	// deliberately NOT a user session token: monitoring is a machine caller and
	// must not require, or be satisfied by, a person's Clerk session. Empty
	// leaves the endpoint open, which the server refuses to do on a public bind.
	MetricsToken string
	// PythonBaseURL is the single source of truth for the internal Python FastAPI
	// base URL that Go proxies cognition, tts, memory, and anchor requests to.
	PythonBaseURL string
	// AllowedOrigins is the CORS allow-list for /api/* responses and the /ws origin check.
	AllowedOrigins []string
	// Rate-limit params for the paid endpoints (per-caller bucket + global ceiling).
	RateLimitRPS         float64
	RateLimitBurst       int
	RateLimitGlobalRPS   float64
	RateLimitGlobalBurst int
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
	_ = godotenv.Load()

	port := 8080
	if v := os.Getenv("PORT"); v != "" {
		if p, err := strconv.Atoi(v); err == nil {
			port = p
		}
	}

	debug := false
	if v := os.Getenv("DEBUG"); v == "true" || v == "1" {
		debug = true
	}

	host := os.Getenv("HOST")
	if host == "" {
		host = "127.0.0.1"
	}

	pythonBin := os.Getenv("PYTHON_BIN")
	if pythonBin == "" {
		pythonBin = "python3"
	}

	audioScript := os.Getenv("AUDIO_SCRIPT")
	if audioScript == "" {
		audioScript = "app/pipeline/audio_worker.py"
	}

	audioEnabled := true
	if v := os.Getenv("AUDIO_ENABLED"); v == "false" || v == "0" {
		audioEnabled = false
	}

	audioMaxSessions := 8
	if v := os.Getenv("AUDIO_MAX_SESSIONS"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			audioMaxSessions = n
		}
	}
	if audioMaxSessions < 1 {
		audioMaxSessions = 1
	}

	ttsProvider := os.Getenv("TTS_PROVIDER")
	if ttsProvider == "" {
		ttsProvider = "elevenlabs"
	}

	elevenLabsVoiceID := os.Getenv("ELEVENLABS_VOICE_ID")
	if elevenLabsVoiceID == "" {
		elevenLabsVoiceID = "21m00Tcm4TlvDq8ikWAM"
	}

	whisperModel := os.Getenv("WHISPER_MODEL")
	if whisperModel == "" {
		whisperModel = "base"
	}

	// Which compute device the transcriber uses. "cpu" is the default because
	// that is what production has always run; "auto" lets faster-whisper pick.
	// The worker validates the value and refuses an unknown one at startup.
	whisperDevice := os.Getenv("WHISPER_DEVICE")
	if whisperDevice == "" {
		whisperDevice = "cpu"
	}

	pythonBaseURL := os.Getenv("PYTHON_BASE_URL")
	if pythonBaseURL == "" {
		pythonBaseURL = "http://127.0.0.1:8000"
	}

	allowedOrigins := parseAllowedOrigins(os.Getenv("ALLOWED_ORIGINS"))

	rateLimitRPS := 5.0
	if v := os.Getenv("RATE_LIMIT_RPS"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			rateLimitRPS = f
		}
	}

	rateLimitBurst := 10
	if v := os.Getenv("RATE_LIMIT_BURST"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			rateLimitBurst = n
		}
	}

	rateLimitGlobalRPS := 50.0
	if v := os.Getenv("RATE_LIMIT_GLOBAL_RPS"); v != "" {
		if f, err := strconv.ParseFloat(v, 64); err == nil {
			rateLimitGlobalRPS = f
		}
	}

	rateLimitGlobalBurst := 100
	if v := os.Getenv("RATE_LIMIT_GLOBAL_BURST"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			rateLimitGlobalBurst = n
		}
	}

	return &Config{
		Host:                 host,
		Port:                 port,
		PythonBin:            pythonBin,
		AnthropicKey:         os.Getenv("ANTHROPIC_API_KEY"),
		ElevenLabsKey:        os.Getenv("ELEVENLABS_API_KEY"),
		Debug:                debug,
		AudioScript:          audioScript,
		AudioEnabled:         audioEnabled,
		AudioMaxSessions:     audioMaxSessions,
		TTSProvider:          ttsProvider,
		ElevenLabsVoiceID:    elevenLabsVoiceID,
		WhisperModel:         whisperModel,
		WhisperDevice:        whisperDevice,
		ClerkSecretKey:       os.Getenv("CLERK_SECRET_KEY"),
		ClerkJWTIssuer:       os.Getenv("CLERK_JWT_ISSUER"),
		InternalAuthSecret:   os.Getenv("INTERNAL_AUTH_SECRET"),
		MetricsToken:         os.Getenv("METRICS_TOKEN"),
		PythonBaseURL:        pythonBaseURL,
		AllowedOrigins:       allowedOrigins,
		RateLimitRPS:         rateLimitRPS,
		RateLimitBurst:       rateLimitBurst,
		RateLimitGlobalRPS:   rateLimitGlobalRPS,
		RateLimitGlobalBurst: rateLimitGlobalBurst,
	}
}

// parseAllowedOrigins splits a comma-separated origin list, trimming blanks.
// It returns the localhost defaults when raw is empty or has no valid entries.
func parseAllowedOrigins(raw string) []string {
	origins := make([]string, 0)
	for _, part := range strings.Split(raw, ",") {
		if o := strings.TrimSpace(part); o != "" {
			origins = append(origins, o)
		}
	}
	if len(origins) == 0 {
		return defaultAllowedOrigins
	}
	return origins
}

// Addr returns the host:port string for the HTTP listener.
func (c *Config) Addr() string {
	return fmt.Sprintf("%s:%d", c.Host, c.Port)
}

package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	"github.com/joho/godotenv"
)

// Config holds all runtime configuration for the server.
type Config struct {
	Host              string
	Port              int
	PythonBin         string
	VisionScript      string
	AnthropicKey      string
	ElevenLabsKey     string
	Debug             bool
	AudioScript       string
	AudioEnabled      bool
	TTSProvider       string
	ElevenLabsVoiceID string
	WhisperModel      string
	CognitionGRPCAddr string
	NatsURL           string
	ClerkSecretKey    string
	ClerkJWTIssuer    string
	AllowedOrigins    []string
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

	visionScript := os.Getenv("VISION_SCRIPT")
	if visionScript == "" {
		visionScript = "app/pipeline/vision_worker.py"
	}

	audioScript := os.Getenv("AUDIO_SCRIPT")
	if audioScript == "" {
		audioScript = "app/pipeline/audio_worker.py"
	}

	audioEnabled := true
	if v := os.Getenv("AUDIO_ENABLED"); v == "false" || v == "0" {
		audioEnabled = false
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

	cognitionGRPCAddr := os.Getenv("COGNITION_GRPC_ADDR")
	if cognitionGRPCAddr == "" {
		cognitionGRPCAddr = "127.0.0.1:50052"
	}

	natsURL := os.Getenv("NATS_URL")
	if natsURL == "" {
		natsURL = "nats://127.0.0.1:4222"
	}

	return &Config{
		Host:              host,
		Port:              port,
		PythonBin:         pythonBin,
		VisionScript:      visionScript,
		AnthropicKey:      os.Getenv("ANTHROPIC_API_KEY"),
		ElevenLabsKey:     os.Getenv("ELEVENLABS_API_KEY"),
		Debug:             debug,
		AudioScript:       audioScript,
		AudioEnabled:      audioEnabled,
		TTSProvider:       ttsProvider,
		ElevenLabsVoiceID: elevenLabsVoiceID,
		WhisperModel:      whisperModel,
		CognitionGRPCAddr: cognitionGRPCAddr,
		NatsURL:           natsURL,
		ClerkSecretKey:    os.Getenv("CLERK_SECRET_KEY"),
		ClerkJWTIssuer:    os.Getenv("CLERK_JWT_ISSUER"),
		AllowedOrigins:    parseOrigins(os.Getenv("ALLOWED_ORIGINS")),
	}
}

// Addr returns the host:port string for the HTTP listener.
func (c *Config) Addr() string {
	return fmt.Sprintf("%s:%d", c.Host, c.Port)
}

// parseOrigins splits a comma-separated ALLOWED_ORIGINS value into a trimmed
// list of allowed WebSocket origins, falling back to the local dev origins.
func parseOrigins(raw string) []string {
	defaults := []string{"http://localhost:3000", "http://127.0.0.1:3000"}
	if strings.TrimSpace(raw) == "" {
		return defaults
	}
	origins := make([]string, 0)
	for _, part := range strings.Split(raw, ",") {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			origins = append(origins, trimmed)
		}
	}
	if len(origins) == 0 {
		return defaults
	}
	return origins
}

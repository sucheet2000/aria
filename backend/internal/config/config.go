package config

import (
	"fmt"
	"os"
	"strconv"
)

// Config holds all runtime configuration for the server.
type Config struct {
	Host          string
	Port          int
	PythonBin     string
	VisionScript  string
	AnthropicKey  string
	ElevenLabsKey string
	Debug         bool
}

// Load reads configuration from environment variables with sensible defaults.
func Load() *Config {
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
		host = "0.0.0.0"
	}

	pythonBin := os.Getenv("PYTHON_BIN")
	if pythonBin == "" {
		pythonBin = "python3"
	}

	visionScript := os.Getenv("VISION_SCRIPT")
	if visionScript == "" {
		visionScript = "app/pipeline/vision_worker.py"
	}

	return &Config{
		Host:          host,
		Port:          port,
		PythonBin:     pythonBin,
		VisionScript:  visionScript,
		AnthropicKey:  os.Getenv("ANTHROPIC_API_KEY"),
		ElevenLabsKey: os.Getenv("ELEVENLABS_API_KEY"),
		Debug:         debug,
	}
}

// Addr returns the host:port string for the HTTP listener.
func (c *Config) Addr() string {
	return fmt.Sprintf("%s:%d", c.Host, c.Port)
}

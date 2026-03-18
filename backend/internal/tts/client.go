package tts

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// Client handles text-to-speech synthesis.
type Client struct {
	apiKey     string
	voiceID    string
	httpClient *http.Client
	log        zerolog.Logger
}

// New creates a new TTS client with the given API key and voice ID.
func New(apiKey, voiceID string) *Client {
	return &Client{
		apiKey:  apiKey,
		voiceID: voiceID,
		httpClient: &http.Client{
			Timeout: 30 * time.Second,
		},
		log: log.With().Str("component", "tts-client").Logger(),
	}
}

type elevenLabsRequest struct {
	Text          string        `json:"text"`
	ModelID       string        `json:"model_id"`
	VoiceSettings voiceSettings `json:"voice_settings"`
}

type voiceSettings struct {
	Stability       float64 `json:"stability"`
	SimilarityBoost float64 `json:"similarity_boost"`
}

// Stream synthesizes text and writes the resulting audio to w.
// When apiKey is empty it falls back to the macOS say command.
func (c *Client) Stream(ctx context.Context, text string, w io.Writer) error {
	if c.apiKey == "" {
		return c.streamLocal(ctx, text, w)
	}
	return c.streamElevenLabs(ctx, text, w)
}

func (c *Client) streamElevenLabs(ctx context.Context, text string, w io.Writer) error {
	url := fmt.Sprintf("https://api.elevenlabs.io/v1/text-to-speech/%s/stream", c.voiceID)

	body := elevenLabsRequest{
		Text:    text,
		ModelID: "eleven_turbo_v2",
		VoiceSettings: voiceSettings{
			Stability:       0.5,
			SimilarityBoost: 0.75,
		},
	}

	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("xi-api-key", c.apiKey)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "audio/mpeg")

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("elevenlabs request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("elevenlabs returned status %d", resp.StatusCode)
	}

	_, err = io.Copy(w, resp.Body)
	return err
}

func (c *Client) streamLocal(ctx context.Context, text string, w io.Writer) error {
	c.log.Warn().Msg("ELEVENLABS_API_KEY not set, using system TTS fallback")

	tmp, err := os.CreateTemp("", "aria-tts-*.aiff")
	if err != nil {
		return fmt.Errorf("create temp file: %w", err)
	}
	defer os.Remove(tmp.Name())
	tmp.Close()

	cmd := exec.CommandContext(ctx, "say", "-v", "Samantha", "--data-format=aiff", "-o", tmp.Name(), text)
	if err := cmd.Run(); err != nil {
		return fmt.Errorf("say command: %w", err)
	}

	f, err := os.Open(tmp.Name())
	if err != nil {
		return fmt.Errorf("open temp file: %w", err)
	}
	defer f.Close()

	_, err = io.Copy(w, f)
	return err
}

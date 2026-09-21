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
	"runtime"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// maxErrorBodyBytes caps how much of a non-2xx upstream response body is
// drained before the connection is released; the body is never logged.
const maxErrorBodyBytes = 4 << 10

// Client handles text-to-speech synthesis.
type Client struct {
	apiKey             string
	voiceID            string
	pythonURL          string
	internalAuthSecret string
	httpClient         *http.Client
	log                zerolog.Logger
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

// SetPythonURL sets the Python TTS proxy endpoint. The composition root wires
// this from config so the Python base URL has a single source of truth.
func (c *Client) SetPythonURL(url string) {
	c.pythonURL = url
}

// SetInternalAuthSecret sets the shared secret sent as X-Internal-Auth on
// requests to the Python service. Empty leaves the header unset (local dev).
func (c *Client) SetInternalAuthSecret(secret string) {
	c.internalAuthSecret = secret
}

type proxyRequest struct {
	Text    string `json:"text"`
	Emotion string `json:"emotion,omitempty"`
}

// haveSayBinary reports whether the macOS `say` command is actually on PATH.
func haveSayBinary() bool {
	_, err := exec.LookPath("say")
	return err == nil
}

// localFallbackAvailable reports whether this machine can synthesize speech
// locally. The fallback shells out to `say`, which ships with macOS and exists
// nowhere else — so on the Linux hosts this actually deploys to there is no
// fallback at all, and pretending otherwise turned a dead Python service into a
// silent, truncated 200 rather than an error anyone could act on.
func localFallbackAvailable() bool {
	return localFallbackCheck()
}

// localFallbackCheck is a variable so tests can exercise BOTH platforms'
// behaviour. Production runs on Linux while development runs on macOS, and the
// path that matters most is the one the developer's machine never takes.
var localFallbackCheck = func() bool {
	return runtime.GOOS == "darwin" && haveSayBinary()
}

// Stream synthesizes text and writes the resulting audio to w.
// Proxies to the Python voice engine's TTS endpoint. On macOS, and only there,
// it can fall back to the system `say` command; elsewhere a proxy failure is
// reported as a failure instead of being papered over.
func (c *Client) Stream(ctx context.Context, text string, emotion string, w io.Writer) error {
	err := c.streamProxy(ctx, text, emotion, w)
	if err == nil {
		return nil
	}
	if !localFallbackAvailable() {
		c.log.Error().Err(err).Str("goos", runtime.GOOS).
			Msg("python TTS proxy failed and no local fallback exists on this platform")
		return fmt.Errorf("tts unavailable: proxy failed and no local synthesizer on %s: %w",
			runtime.GOOS, err)
	}
	c.log.Warn().Err(err).Msg("python TTS proxy failed, falling back to local")
	return c.streamLocal(ctx, text, w)
}

func (c *Client) streamProxy(ctx context.Context, text string, emotion string, w io.Writer) error {
	body := proxyRequest{
		Text:    text,
		Emotion: emotion,
	}

	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.pythonURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if owner := auth.OwnerFromContext(ctx); owner != "" {
		req.Header.Set(auth.OwnerHeader, owner)
	}
	auth.SetInternalAuth(req, c.internalAuthSecret)
	reqid.SetHeader(req, ctx)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("proxy request: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		// S2: drain (bounded) but never embed the body — the error is logged and
		// a validation body can echo the text being spoken.
		n, _ := io.Copy(io.Discard, io.LimitReader(resp.Body, maxErrorBodyBytes))
		return fmt.Errorf("tts upstream returned %d (%d body bytes)", resp.StatusCode, n)
	}

	_, err = io.Copy(w, resp.Body)
	return err
}

func (c *Client) streamLocal(ctx context.Context, text string, w io.Writer) error {
	c.log.Warn().Msg("using system TTS fallback")

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

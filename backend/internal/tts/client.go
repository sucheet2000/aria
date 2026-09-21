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

// Open returns a reader for the synthesized speech, or an error when no speech
// can be produced at all.
//
// The handler needs to know whether a stream exists BEFORE it commits success
// headers. Streaming straight into the ResponseWriter meant the status was
// already sent by the time a failure surfaced, so a dead provider reached the
// caller as a 200 carrying an empty audio body — indistinguishable from ARIA
// choosing to say nothing. Nothing is buffered: on the proxy path this is the
// upstream response body itself, and the caller closes it.
func (c *Client) Open(ctx context.Context, text string, emotion string) (io.ReadCloser, error) {
	body, err := c.openProxy(ctx, text, emotion)
	if err == nil {
		return body, nil
	}
	if !localFallbackAvailable() {
		c.log.Error().Err(err).Str("goos", runtime.GOOS).
			Msg("python TTS proxy failed and no local fallback exists on this platform")
		return nil, fmt.Errorf("tts unavailable: proxy failed and no local synthesizer on %s: %w",
			runtime.GOOS, err)
	}
	c.log.Warn().Err(err).Msg("python TTS proxy failed, falling back to local")
	return c.openLocal(ctx, text)
}

// openProxy performs the upstream request and hands back its body on success.
// The caller owns closing it.
func (c *Client) openProxy(ctx context.Context, text string, emotion string) (io.ReadCloser, error) {
	body := proxyRequest{Text: text, Emotion: emotion}

	bodyBytes, err := json.Marshal(body)
	if err != nil {
		return nil, fmt.Errorf("marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.pythonURL, bytes.NewReader(bodyBytes))
	if err != nil {
		return nil, fmt.Errorf("create request: %w", err)
	}

	req.Header.Set("Content-Type", "application/json")
	if owner := auth.OwnerFromContext(ctx); owner != "" {
		req.Header.Set(auth.OwnerHeader, owner)
	}
	auth.SetInternalAuth(req, c.internalAuthSecret)
	reqid.SetHeader(req, ctx)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("proxy request: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		// S2: drain (bounded) but never embed the body — a validation message
		// can echo the text being spoken.
		n, _ := io.Copy(io.Discard, io.LimitReader(resp.Body, maxErrorBodyBytes))
		resp.Body.Close()
		return nil, fmt.Errorf("tts upstream returned %d (%d body bytes)", resp.StatusCode, n)
	}
	return resp.Body, nil
}

// openLocal synthesizes with the system voice and returns the finished file.
// It is only reached where localFallbackAvailable() is true.
func (c *Client) openLocal(ctx context.Context, text string) (io.ReadCloser, error) {
	tmp, err := os.CreateTemp("", "aria-tts-*.aiff")
	if err != nil {
		return nil, fmt.Errorf("create temp file: %w", err)
	}
	name := tmp.Name()
	tmp.Close()

	cmd := exec.CommandContext(ctx, "say", "-v", "Samantha", "--data-format=aiff", "-o", name, text)
	if err := cmd.Run(); err != nil {
		os.Remove(name)
		return nil, fmt.Errorf("say command: %w", err)
	}

	f, err := os.Open(name)
	if err != nil {
		os.Remove(name)
		return nil, fmt.Errorf("open temp file: %w", err)
	}
	// The file is unlinked now; the open handle keeps the bytes alive until the
	// caller closes it, so there is nothing to clean up afterwards.
	os.Remove(name)
	return f, nil
}

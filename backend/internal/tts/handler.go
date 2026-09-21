package tts

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"
	"unicode/utf8"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

const maxTextLength = 500

// truncateForSpeech caps the text at maxTextLength BYTES, which is what the
// provider limit counts, without ever splitting a rune. A byte slice alone
// would cut a multi-byte character in half and put invalid UTF-8 on the wire —
// silently, since nothing downstream validates it. A rune that straddles the
// cap is dropped whole.
func truncateForSpeech(text string) string {
	if len(text) <= maxTextLength {
		return text
	}
	cut := maxTextLength
	for cut > 0 && !utf8.RuneStart(text[cut]) {
		cut--
	}
	return text[:cut]
}

// maxRequestBodyBytes caps the /api/tts request body. Over-cap requests
// surface as 413.
const maxRequestBodyBytes = 64 << 10

// TTSRequest is the JSON body for POST /api/tts.
type TTSRequest struct {
	Text    string `json:"text"`
	VoiceID string `json:"voice_id,omitempty"`
	Emotion string `json:"emotion,omitempty"`
}

// Handler serves HTTP requests for TTS synthesis.
type Handler struct {
	client *Client
	log    zerolog.Logger
}

// NewHandler creates a new Handler backed by client.
func NewHandler(client *Client) *Handler {
	return &Handler{
		client: client,
		log:    log.With().Str("component", "tts-handler").Logger(),
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyBytes)

	var req TTSRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			w.Write([]byte(`{"error":"request body too large"}`)) //nolint:errcheck
			return
		}
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Text == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"error":"text is required"}`))
		return
	}

	req.Text = truncateForSpeech(req.Text)

	start := time.Now()

	// Open the stream BEFORE announcing success. Setting the audio headers first
	// committed a 200 on the first byte, so a dead provider reached the caller as
	// an empty audio body that looked exactly like ARIA choosing to say nothing.
	stream, err := h.client.Open(r.Context(), req.Text, req.Emotion)
	if err != nil {
		h.log.Error().Err(err).Msg("tts stream failed")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusServiceUnavailable)
		// S2: the cause is logged, never echoed — an upstream body can quote the
		// text being spoken.
		w.Write([]byte(`{"error":"speech synthesis unavailable"}`)) //nolint:errcheck
		return
	}
	defer stream.Close()

	w.Header().Set("Content-Type", "audio/mpeg")
	w.Header().Set("Transfer-Encoding", "chunked")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Content-Type-Options", "nosniff")

	if _, err := io.Copy(w, stream); err != nil {
		// The status is already sent; all that is left is to record it.
		h.log.Error().Err(err).Msg("tts stream interrupted after headers")
	}

	h.log.Info().
		Int("text_length", len(req.Text)).
		Dur("duration", time.Since(start)).
		Msg("tts request completed")
}

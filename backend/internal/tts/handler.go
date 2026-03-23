package tts

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

const maxTextLength = 500

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

	var req TTSRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, `{"error":"invalid request body"}`, http.StatusBadRequest)
		return
	}

	if req.Text == "" {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte(`{"error":"text is required"}`))
		return
	}

	if len(req.Text) > maxTextLength {
		req.Text = req.Text[:maxTextLength]
	}

	w.Header().Set("Content-Type", "audio/mpeg")
	w.Header().Set("Transfer-Encoding", "chunked")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("X-Content-Type-Options", "nosniff")

	start := time.Now()

	if err := h.client.Stream(r.Context(), req.Text, req.Emotion, w); err != nil {
		h.log.Error().Err(err).Msg("tts stream failed")
	}

	h.log.Info().
		Int("text_length", len(req.Text)).
		Dur("duration", time.Since(start)).
		Msg("tts request completed")
}

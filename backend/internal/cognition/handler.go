package cognition

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/rs/zerolog"
)

// maxRequestBodyBytes caps the /api/cognition request body to guard against
// oversized payloads. Over-cap requests surface as 413.
const maxRequestBodyBytes = 64 << 10

// PerceptionFrame holds the browser's derived perception state for one turn.
// EmotionConfidence is the browser's heuristic facial-affect score in [0, 1]
// (canonical wire field `emotion_confidence`); nil means the browser had no
// perception frame to report. Go forwards it verbatim: it never computes,
// defaults or clamps it, so an absent value stays absent for Python.
type PerceptionFrame struct {
	Emotion           string   `json:"emotion"`
	EmotionConfidence *float64 `json:"emotion_confidence,omitempty"`
	Pitch             float64  `json:"pitch"`
	Yaw               float64  `json:"yaw"`
	Roll              float64  `json:"roll"`
	FaceDetected      bool     `json:"face_detected"`
	HandsDetected     bool     `json:"hands_detected"`
}

// ConversationTurn represents a single role/content pair in conversation history.
type ConversationTurn struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// CognitionRequest is the body the browser (or Go→Python proxy) sends.
type CognitionRequest struct {
	Message             string             `json:"message"`
	VisionState         PerceptionFrame    `json:"vision_state"`
	ConversationHistory []ConversationTurn `json:"conversation_history"`
	SessionID           string             `json:"session_id,omitempty"`
	// Gesture fields forwarded verbatim to the Python spatial pipeline.
	Gesture        string    `json:"gesture"`
	TwoHandGesture string    `json:"two_hand_gesture"`
	PointingVector []float64 `json:"pointing_vector"`
}

// WorldModelTriple is a subject/predicate/object fact triple.
type WorldModelTriple struct {
	Subject   string `json:"subject"`
	Predicate string `json:"predicate"`
	Object    string `json:"object"`
}

// WorldModelUpdate wraps a fact triple with provenance metadata.
type WorldModelUpdate struct {
	Triple     WorldModelTriple `json:"triple"`
	Confidence float64          `json:"confidence"`
	Source     string           `json:"source"`
}

// CognitionResponse is the structured neurosymbolic response sent to the browser.
type CognitionResponse struct {
	SymbolicInference       string            `json:"symbolic_inference"`
	WorldModelUpdate        *WorldModelUpdate `json:"world_model_update"`
	NaturalLanguageResponse string            `json:"natural_language_response"`
	AvatarEmotion           string            `json:"avatar_emotion"`
	ProcessingMs            int64             `json:"processing_ms"`
	EpisodicMemory          []string          `json:"episodic_memory,omitempty"`
	// SpatialEvent is passed through from Python unchanged. json.RawMessage keeps
	// Go schema-agnostic; the frontend's handleSpatialEvent() owns deserialization.
	SpatialEvent json.RawMessage `json:"spatial_event,omitempty"`
}

type errorResponse struct {
	Error string `json:"error"`
}

// Handler handles POST /api/cognition.
type Handler struct {
	client *Client
	log    zerolog.Logger
}

// NewHandler creates a Handler with the given cognition client.
func NewHandler(client *Client, log zerolog.Logger) *Handler {
	return &Handler{client: client, log: log}
}

// ServeHTTP implements http.Handler.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
		return
	}

	if r.Body == nil {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "request body is required"})
		return
	}

	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBodyBytes)

	var req CognitionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeJSON(w, http.StatusRequestEntityTooLarge, errorResponse{Error: "request body too large"})
			return
		}
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "invalid request body"})
		return
	}

	if req.Message == "" {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "message is required"})
		return
	}

	sessionID := req.SessionID
	if sessionID == "" {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "session_id is required"})
		return
	}
	if c := req.VisionState.EmotionConfidence; c != nil && (*c < 0 || *c > 1) {
		h.log.Warn().Msg("cognition request rejected: emotion_confidence out of range")
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "emotion_confidence must be between 0 and 1"})
		return
	}
	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	result, err := h.client.Complete(ctx, req)
	if err != nil {
		h.log.Error().Err(err).Msg("cognition complete failed")
		writeJSON(w, http.StatusInternalServerError, errorResponse{Error: "internal server error"})
		return
	}

	h.log.Info().
		Str("method", r.Method).
		Str("path", r.URL.Path).
		Int("status", http.StatusOK).
		Int64("processing_ms", result.ProcessingMs).
		Str("avatar_emotion", result.AvatarEmotion).
		Msg("cognition request handled")

	writeJSON(w, http.StatusOK, result)
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

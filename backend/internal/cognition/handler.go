package cognition

import (
	"encoding/json"
	"net/http"

	"github.com/rs/zerolog"
)

// httpRequest mirrors the JSON body the frontend sends.
type httpRequest struct {
	Message             string               `json:"message"`
	VisionState         visionStateJSON      `json:"vision_state"`
	ConversationHistory []conversationTurnJSON `json:"conversation_history"`
}

type visionStateJSON struct {
	Emotion       string       `json:"emotion"`
	HeadPose      headPoseJSON `json:"head_pose"`
	FaceDetected  bool         `json:"face_detected"`
	HandsDetected bool         `json:"hands_detected"`
}

type headPoseJSON struct {
	Pitch float64 `json:"pitch"`
	Yaw   float64 `json:"yaw"`
	Roll  float64 `json:"roll"`
}

type conversationTurnJSON struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// httpResponse mirrors the JSON body sent back to the frontend.
type httpResponse struct {
	Response          string `json:"response"`
	EmotionSuggestion string `json:"emotion_suggestion"`
	ProcessingMs      int64  `json:"processing_ms"`
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

	var req httpRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "invalid request body"})
		return
	}

	if req.Message == "" {
		writeJSON(w, http.StatusBadRequest, errorResponse{Error: "message is required"})
		return
	}

	history := make([]ConversationMessage, 0, len(req.ConversationHistory))
	for _, turn := range req.ConversationHistory {
		history = append(history, ConversationMessage{
			Role:    turn.Role,
			Content: turn.Content,
		})
	}

	cogReq := CognitionRequest{
		Message: req.Message,
		VisionState: VisionStateContext{
			Emotion:       req.VisionState.Emotion,
			Pitch:         req.VisionState.HeadPose.Pitch,
			Yaw:           req.VisionState.HeadPose.Yaw,
			Roll:          req.VisionState.HeadPose.Roll,
			FaceDetected:  req.VisionState.FaceDetected,
			HandsDetected: req.VisionState.HandsDetected,
		},
		ConversationHistory: history,
	}

	result, err := h.client.Complete(r.Context(), cogReq)
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
		Str("emotion_suggestion", result.EmotionSuggestion).
		Msg("cognition request handled")

	writeJSON(w, http.StatusOK, httpResponse{
		Response:          result.Response,
		EmotionSuggestion: result.EmotionSuggestion,
		ProcessingMs:      result.ProcessingMs,
	})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(v)
}

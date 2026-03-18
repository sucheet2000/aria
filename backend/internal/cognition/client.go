package cognition

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// Client forwards cognition requests to the Python FastAPI service and enriches
// them with working memory.
type Client struct {
	pythonServiceURL string
	httpClient       *http.Client
	workingMemory    *memory.WorkingMemory
	log              zerolog.Logger
}

// New creates a Client that proxies to the given Python service URL.
func New(pythonServiceURL string, wm *memory.WorkingMemory) *Client {
	return &Client{
		pythonServiceURL: pythonServiceURL,
		httpClient:       &http.Client{Timeout: 30 * time.Second},
		workingMemory:    wm,
		log:              zerolog.Nop(),
	}
}

// NewWithLogger creates a Client with a named logger.
func NewWithLogger(pythonServiceURL string, wm *memory.WorkingMemory, log zerolog.Logger) *Client {
	c := New(pythonServiceURL, wm)
	c.log = log
	return c
}

// enrichedRequest extends CognitionRequest with memory fields forwarded to Python.
type enrichedRequest struct {
	CognitionRequest
	WorkingMemory  []string `json:"working_memory"`
	EpisodicMemory []string `json:"episodic_memory"`
}

// Complete enriches the request with working memory, posts it to the Python
// cognition service, stores the returned symbolic inference, and derives the
// avatar emotion.
func (c *Client) Complete(ctx context.Context, req CognitionRequest) (CognitionResponse, error) {
	start := time.Now()

	enriched := enrichedRequest{
		CognitionRequest: req,
		WorkingMemory:    c.workingMemory.Last(5),
		EpisodicMemory:   []string{},
	}

	body, err := json.Marshal(enriched)
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("marshal cognition request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.pythonServiceURL, bytes.NewReader(body))
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("build http request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")

	httpResp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("python cognition service: %w", err)
	}
	defer httpResp.Body.Close()

	var resp CognitionResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return CognitionResponse{}, fmt.Errorf("decode cognition response: %w", err)
	}

	if resp.SymbolicInference != "" {
		c.workingMemory.Push(resp.SymbolicInference)
	}

	resp.ProcessingMs = time.Since(start).Milliseconds()
	resp.AvatarEmotion = suggestAvatarEmotion(resp.SymbolicInference)
	return resp, nil
}

// suggestAvatarEmotion maps keywords in a symbolic inference string to an
// avatar emotion label.
func suggestAvatarEmotion(inference string) string {
	lower := strings.ToLower(inference)

	switch {
	case containsAnyKeyword(lower, "blocked", "frustrated", "stuck"):
		return "frustrated"
	case containsAnyKeyword(lower, "distressed", "stressed", "worried"):
		return "fearful"
	case containsAnyKeyword(lower, "focused", "working", "building"):
		return "neutral"
	case containsAnyKeyword(lower, "happy", "excited", "progress"):
		return "happy"
	case containsAnyKeyword(lower, "confused", "unclear", "lost"):
		return "surprised"
	default:
		return "neutral"
	}
}

func containsAnyKeyword(s string, keywords ...string) bool {
	for _, kw := range keywords {
		if strings.Contains(s, kw) {
			return true
		}
	}
	return false
}

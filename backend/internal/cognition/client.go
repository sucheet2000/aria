package cognition

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/memory"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// maxErrorBodyBytes caps how much of a non-2xx upstream response body is
// drained before the connection is released; the body is never logged.
const maxErrorBodyBytes = 4 << 10

// UpstreamTimeout is Go's slice of the cross-layer deadline budget, which is
// ordered browser 25s > Go upstream 20s > Python total 15s >= provider attempt
// 10s. Each layer must stay strictly above the one it waits on and strictly
// below the one waiting on it: raise this above the browser's window and the
// caller gives up first, lower it under Python's total and Go abandons work
// Python is still paying for.
const UpstreamTimeout = 20 * time.Second

// DeadlineHeader carries the caller's remaining budget, in whole milliseconds,
// to Python so it can size its own attempt instead of guessing.
const DeadlineHeader = "X-Aria-Deadline-Ms"

// ErrUpstreamTimeout marks a 504 from Python. Python's total budget (15s) is
// deliberately shorter than ours (20s), so Python giving up is the EXPECTED
// timeout path: it must surface as a gateway timeout, not as a server error.
var ErrUpstreamTimeout = errors.New("cognition upstream timed out")

// Client forwards cognition requests to the Python FastAPI service and enriches
// them with working memory (the last few symbolic inferences).
//
// Durable semantic memory (profile/episodic facts) is NOT held here: Python is
// its single source of truth and retrieves it per turn (S3). Go used to cache
// the previous turn's episodic list and replay it, which resurrected deleted
// facts; that cache is gone.
type Client struct {
	pythonServiceURL   string
	httpClient         *http.Client
	workingMemory      *memory.WorkingMemory
	log                zerolog.Logger
	internalAuthSecret string
	upstreamTimeout    time.Duration
}

// UpstreamTimeout returns the budget the caller should give one cognition turn.
func (c *Client) UpstreamTimeout() time.Duration { return c.upstreamTimeout }

// SetUpstreamTimeout overrides the budget. Tests use it to inject a budget
// small enough to expire without a real wait; production keeps the default.
func (c *Client) SetUpstreamTimeout(d time.Duration) { c.upstreamTimeout = d }

// New creates a Client that proxies to the given Python service URL.
func New(pythonServiceURL string, wm *memory.WorkingMemory) *Client {
	return &Client{
		pythonServiceURL: pythonServiceURL,
		// The per-request context deadline is the real bound; this is only a
		// backstop for a caller that passes no deadline. Keeping it above
		// UpstreamTimeout ensures a normal timeout surfaces as a clean
		// context.DeadlineExceeded rather than the http.Client's own generic
		// timeout error, which the handler cannot classify into a 504.
		httpClient:      &http.Client{Timeout: UpstreamTimeout + 5*time.Second},
		workingMemory:   wm,
		log:             zerolog.Nop(),
		upstreamTimeout: UpstreamTimeout,
	}
}

// NewWithLogger creates a Client with a named logger.
func NewWithLogger(pythonServiceURL string, wm *memory.WorkingMemory, log zerolog.Logger) *Client {
	c := New(pythonServiceURL, wm)
	c.log = log
	return c
}

// SetInternalAuthSecret sets the shared secret sent as X-Internal-Auth on
// requests to the Python service. Empty leaves the header unset (local dev).
func (c *Client) SetInternalAuthSecret(secret string) {
	c.internalAuthSecret = secret
}

// enrichedRequest extends CognitionRequest with the working-memory field
// forwarded to Python. Episodic memory is deliberately absent: Python retrieves
// it from the store for every turn.
type enrichedRequest struct {
	CognitionRequest
	WorkingMemory []string `json:"working_memory"`
}

// Complete enriches the request with working memory, posts it to the Python
// cognition service, stores the returned symbolic inference, and derives the
// avatar emotion.
func (c *Client) Complete(ctx context.Context, req CognitionRequest) (CognitionResponse, error) {
	start := time.Now()
	owner := auth.OwnerFromContext(ctx)
	// If the owner deletes their memory while this turn is in flight, the
	// inference it produces was based on pre-delete facts and must not be
	// pushed back into the freshly cleared ring.
	gen := c.workingMemory.Generation(owner)

	enriched := enrichedRequest{
		CognitionRequest: req,
		WorkingMemory:    c.workingMemory.Last(owner, 5),
	}

	body, err := json.Marshal(enriched)
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("marshal cognition request: %w", err)
	}

	remaining, hasDeadline := remainingBudget(ctx)
	if hasDeadline && remaining <= 0 {
		// The caller can no longer wait for an answer, so spending an upstream
		// turn on one would cost money for a response nobody reads.
		return CognitionResponse{}, fmt.Errorf("cognition budget already expired: %w", context.DeadlineExceeded)
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, c.pythonServiceURL, bytes.NewReader(body))
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("build http request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	if hasDeadline {
		// Round a sub-millisecond remainder UP to 1ms: floor()ing it to 0 would
		// drop the header and let Python take its full budget while we expire.
		ms := remaining.Milliseconds()
		if ms < 1 {
			ms = 1
		}
		httpReq.Header.Set(DeadlineHeader, strconv.FormatInt(ms, 10))
	}
	if owner != "" {
		httpReq.Header.Set(auth.OwnerHeader, owner)
	}
	auth.SetInternalAuth(httpReq, c.internalAuthSecret)
	reqid.SetHeader(httpReq, ctx)

	httpResp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("python cognition service: %w", err)
	}
	defer httpResp.Body.Close()

	if httpResp.StatusCode != http.StatusOK {
		// S2: the body is drained (bounded) but never embedded in the error —
		// this error is logged, and a 422 body echoes the user's request text.
		n, _ := io.Copy(io.Discard, io.LimitReader(httpResp.Body, maxErrorBodyBytes))
		if httpResp.StatusCode == http.StatusGatewayTimeout {
			return CognitionResponse{}, fmt.Errorf(
				"cognition upstream returned %d (%d body bytes): %w",
				httpResp.StatusCode, n, ErrUpstreamTimeout,
			)
		}
		return CognitionResponse{}, fmt.Errorf(
			"cognition upstream returned %d (%d body bytes)",
			httpResp.StatusCode,
			n,
		)
	}

	var resp CognitionResponse
	if err := json.NewDecoder(httpResp.Body).Decode(&resp); err != nil {
		return CognitionResponse{}, fmt.Errorf("decode cognition response: %w", err)
	}

	if resp.SymbolicInference != "" {
		// Check-and-push under one lock: a delete that lands between the two
		// would otherwise re-populate the freshly cleared ring.
		c.workingMemory.PushIfGeneration(owner, resp.SymbolicInference, gen)
	}

	// resp.EpisodicMemory (the facts Python retrieved for THIS turn) is passed
	// through to the browser for display only; it is never stored here.
	resp.ProcessingMs = time.Since(start).Milliseconds()
	resp.AvatarEmotion = suggestAvatarEmotion(resp.SymbolicInference)
	return resp, nil
}

// remainingBudget reports how long the caller is still willing to wait. The
// second result is false when the caller set no deadline at all, which is
// distinct from a budget that has run out.
func remainingBudget(ctx context.Context) (time.Duration, bool) {
	deadline, ok := ctx.Deadline()
	if !ok {
		return 0, false
	}
	return time.Until(deadline), true
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
	case containsAnyKeyword(lower, "sad", "unhappy", "disappointed"):
		return "sad"
	case containsAnyKeyword(lower, "angry", "furious", "annoyed"):
		return "angry"
	case containsAnyKeyword(lower, "disgusted", "gross", "repulsed"):
		return "disgusted"
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

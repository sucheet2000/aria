package cognition

import (
	"context"
	"sync"
	"time"
)

const pendingTTL = 10 * time.Second
const maxPendingSize = 32

type pendingEntry struct {
	setAt time.Time
}

// StreamRegistry is a thread-safe map from session_id to context.CancelFunc.
// It bridges the gRPC interrupt path (CognitionGRPCServer) and the HTTP handler
// (Handler.ServeHTTP) so a kill signal from Python cancels the active Claude call.
//
// Race: an interrupt can arrive before the HTTP handler calls Register.
// pending tracks this case — Register immediately cancels if a pending entry exists.
// Pending entries expire after pendingTTL to avoid poisoning future requests.
type StreamRegistry struct {
	mu            sync.Mutex
	active        map[string]context.CancelFunc
	pending       map[string]pendingEntry
	activeSession string
}

// NewStreamRegistry creates an empty registry.
func NewStreamRegistry() *StreamRegistry {
	return &StreamRegistry{
		active:  make(map[string]context.CancelFunc),
		pending: make(map[string]pendingEntry),
	}
}

// ActiveSessionID returns the ID of the most recently registered session, or ""
// if no session is currently active.
func (r *StreamRegistry) ActiveSessionID() string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.activeSession
}

// evictStalePending removes pending entries older than pendingTTL. Caller must
// hold r.mu.
func (r *StreamRegistry) evictStalePending() {
	now := time.Now()
	for id, p := range r.pending {
		if now.Sub(p.setAt) >= pendingTTL {
			delete(r.pending, id)
		}
	}
}

// Note: single cancel func per session is intentional for ARIA v1 (single-user).
// Multi-session concurrent request tracking is a v2 concern tracked in IMPROVEMENT_SCHEME.md.

// Register stores cancel for the given session. If an interrupt arrived before
// this call (pending entry), cancel is called immediately.
func (r *StreamRegistry) Register(id string, cancel context.CancelFunc) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.evictStalePending()
	if p, ok := r.pending[id]; ok {
		if time.Since(p.setAt) < pendingTTL {
			cancel()
			delete(r.pending, id)
			return
		}
		// Stale pending marker — discard and register normally.
		delete(r.pending, id)
	}
	r.active[id] = cancel
	r.activeSession = id
}

// Cancel calls the cancel func for id and removes it. If no entry exists yet
// (interrupt arrived before Register), stores a pending marker.
func (r *StreamRegistry) Cancel(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.evictStalePending()
	if cancel, ok := r.active[id]; ok {
		cancel()
		delete(r.active, id)
	} else {
		if _, exists := r.pending[id]; !exists {
			if len(r.pending) >= maxPendingSize {
				var oldestID string
				var oldestTime time.Time
				for pid, p := range r.pending {
					if oldestID == "" || p.setAt.Before(oldestTime) {
						oldestID = pid
						oldestTime = p.setAt
					}
				}
				delete(r.pending, oldestID)
			}
		}
		r.pending[id] = pendingEntry{setAt: time.Now()}
	}
	if r.activeSession == id {
		r.activeSession = ""
	}
}

// CancelActive cancels whichever session was most recently registered and returns
// its ID. Returns "" if there is no active session. Used when the interrupt
// producer (e.g. vision worker) does not know the active session ID and sends
// session_id="default" instead.
func (r *StreamRegistry) CancelActive() string {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.activeSession == "" {
		return ""
	}
	if cancel, ok := r.active[r.activeSession]; ok {
		cancel()
		delete(r.active, r.activeSession)
		id := r.activeSession
		r.activeSession = ""
		return id
	}
	// activeSession points to an already-removed entry — clear stale ref.
	r.activeSession = ""
	return ""
}

// Unregister removes the entry for id without calling cancel. Called on normal
// HTTP handler completion to prevent a stale cancel func from accumulating.
func (r *StreamRegistry) Unregister(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.evictStalePending()
	delete(r.active, id)
	delete(r.pending, id)
	if r.activeSession == id {
		r.activeSession = ""
	}
}

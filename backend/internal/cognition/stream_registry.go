package cognition

import (
	"context"
	"sync"
	"time"
)

const pendingTTL = 10 * time.Second

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

// Register stores cancel for the given session. If an interrupt arrived before
// this call (pending entry), cancel is called immediately.
func (r *StreamRegistry) Register(id string, cancel context.CancelFunc) {
	r.mu.Lock()
	defer r.mu.Unlock()
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
	if cancel, ok := r.active[id]; ok {
		cancel()
		delete(r.active, id)
	} else {
		r.pending[id] = pendingEntry{setAt: time.Now()}
	}
}

// CancelActive cancels whichever session was most recently registered. Used when
// the interrupt producer (e.g. vision worker) does not know the active session ID
// and sends session_id="default" instead.
func (r *StreamRegistry) CancelActive() {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.activeSession != "" {
		if cancel, ok := r.active[r.activeSession]; ok {
			cancel()
			delete(r.active, r.activeSession)
		}
	}
}

// Unregister removes the entry for id without calling cancel. Called on normal
// HTTP handler completion to prevent a stale cancel func from accumulating.
func (r *StreamRegistry) Unregister(id string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.active, id)
	delete(r.pending, id)
}

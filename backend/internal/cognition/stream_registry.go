package cognition

import (
	"context"
	"sync"
)

// StreamRegistry is a thread-safe map from session_id to context.CancelFunc.
// It bridges the gRPC interrupt path (CognitionGRPCServer) and the HTTP handler
// (Handler.ServeHTTP) so a kill signal from Python cancels the active Claude call.
//
// Race: an interrupt can arrive before the HTTP handler calls Register.
// pending tracks this case — Register immediately cancels if a pending entry exists.
type StreamRegistry struct {
	mu      sync.Mutex
	active  map[string]context.CancelFunc
	pending map[string]struct{}
}

// NewStreamRegistry creates an empty registry.
func NewStreamRegistry() *StreamRegistry {
	return &StreamRegistry{
		active:  make(map[string]context.CancelFunc),
		pending: make(map[string]struct{}),
	}
}

// Register stores cancel for the given session. If an interrupt arrived before
// this call (pending entry), cancel is called immediately.
func (r *StreamRegistry) Register(id string, cancel context.CancelFunc) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.pending[id]; ok {
		cancel()
		delete(r.pending, id)
		return
	}
	r.active[id] = cancel
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
		r.pending[id] = struct{}{}
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

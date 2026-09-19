package memory

import "sync"

// WorkingMemory is a thread-safe, owner-scoped store of symbolic inference
// strings. Each owner gets an independent circular buffer, so entries from one
// owner are never visible to another. The single-user default keys everything
// under the empty owner and behaves like a plain circular buffer.
type WorkingMemory struct {
	mu      sync.RWMutex
	buffers map[string][]string
	gens    map[string]uint64
	maxSize int
}

// New creates a WorkingMemory whose per-owner buffers hold up to maxSize entries.
func New(maxSize int) *WorkingMemory {
	return &WorkingMemory{
		buffers: make(map[string][]string),
		gens:    make(map[string]uint64),
		maxSize: maxSize,
	}
}

// Push appends an inference string to owner's buffer, evicting the oldest entry
// when it is full.
func (w *WorkingMemory) Push(owner, inference string) {
	w.mu.Lock()
	defer w.mu.Unlock()

	entries := append(w.buffers[owner], inference)
	if len(entries) > w.maxSize {
		entries = entries[len(entries)-w.maxSize:]
	}
	w.buffers[owner] = entries
}

// Last returns a copy of the last n entries for owner. If fewer than n entries
// exist, all of owner's entries are returned.
func (w *WorkingMemory) Last(owner string, n int) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	if n <= 0 {
		return []string{}
	}

	entries := w.buffers[owner]
	start := len(entries) - n
	if start < 0 {
		start = 0
	}

	src := entries[start:]
	result := make([]string, len(src))
	copy(result, src)
	return result
}

// All returns a copy of every entry in owner's buffer.
func (w *WorkingMemory) All(owner string) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	entries := w.buffers[owner]
	result := make([]string, len(entries))
	copy(result, entries)
	return result
}

// Clear empties owner's buffer and bumps owner's generation so a caller that
// captured the generation earlier can tell a delete happened meanwhile.
func (w *WorkingMemory) Clear(owner string) {
	w.mu.Lock()
	defer w.mu.Unlock()

	delete(w.buffers, owner)
	w.gens[owner]++
}

// Generation returns how many times owner's buffer has been cleared.
func (w *WorkingMemory) Generation(owner string) uint64 {
	w.mu.RLock()
	defer w.mu.RUnlock()
	return w.gens[owner]
}

// PushIfGeneration appends inference only if owner's generation still equals
// gen, comparing and appending under one lock so a Clear cannot land between
// the check and the write. It reports whether the push happened.
func (w *WorkingMemory) PushIfGeneration(owner, inference string, gen uint64) bool {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.gens[owner] != gen {
		return false
	}
	entries := append(w.buffers[owner], inference)
	if len(entries) > w.maxSize {
		entries = entries[len(entries)-w.maxSize:]
	}
	w.buffers[owner] = entries
	return true
}

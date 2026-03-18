package memory

import "sync"

// WorkingMemory is a thread-safe circular buffer of symbolic inference strings.
type WorkingMemory struct {
	mu      sync.RWMutex
	entries []string
	maxSize int
}

// New creates a WorkingMemory with the given capacity.
func New(maxSize int) *WorkingMemory {
	return &WorkingMemory{
		entries: make([]string, 0, maxSize),
		maxSize: maxSize,
	}
}

// Push appends an inference string, evicting the oldest entry when full.
func (w *WorkingMemory) Push(inference string) {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.entries = append(w.entries, inference)
	if len(w.entries) > w.maxSize {
		w.entries = w.entries[1:]
	}
}

// Last returns a copy of the last n entries. If fewer than n entries exist,
// all entries are returned.
func (w *WorkingMemory) Last(n int) []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	if n <= 0 {
		return []string{}
	}

	start := len(w.entries) - n
	if start < 0 {
		start = 0
	}

	src := w.entries[start:]
	result := make([]string, len(src))
	copy(result, src)
	return result
}

// All returns a copy of every entry in the buffer.
func (w *WorkingMemory) All() []string {
	w.mu.RLock()
	defer w.mu.RUnlock()

	result := make([]string, len(w.entries))
	copy(result, w.entries)
	return result
}

// Clear empties the buffer.
func (w *WorkingMemory) Clear() {
	w.mu.Lock()
	defer w.mu.Unlock()

	w.entries = []string{}
}

package audio

import (
	"context"
	"errors"
	"os"
	"sync"
	"time"

	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
)

// ErrTooManySessions is returned by Acquire when creating a session for a new
// owner would exceed the manager's cap. Existing owners are never refused.
var ErrTooManySessions = errors.New("audio: too many concurrent audio sessions")

// ErrManagerStopped is returned by Acquire after Stop has run.
var ErrManagerStopped = errors.New("audio: session manager stopped")

// mutedOwnerTTL ages out the RETAINED RECORD below — the intent consulted when
// a session is rebuilt. It does NOT bound a mute already applied to a running
// worker: that flag is cleared only by an explicit tts_unmute or by the session
// being torn down. What heals a live session is the browser's resync, which
// re-states the truth every time the control socket opens (resyncTtsMuteState).
// Chosen far longer than any single spoken reply, so a rebuilt session is never
// unmuted mid-sentence, and short enough that a record left by a client which
// never returns does not outlive the conversation.
const mutedOwnerTTL = 60 * time.Second

// TranscriptRouter delivers one transcript envelope to exactly the owner whose
// audio produced it. The composition root binds this to hub.BroadcastToOwner.
type TranscriptRouter func(owner string, data []byte)

// Session is one owner's private STT pipeline: its own Python subprocess, its
// own stdin, its own VAD/wake state (inside that process) and its own mute
// flag. It is refcounted across that owner's concurrent /ws/audio connections.
type Session struct {
	owner    string
	worker   *Worker
	refs     int
	draining bool
	cancel   context.CancelFunc
	done     chan struct{}
}

// SessionManager owns every live audio Session, keyed by the authenticated
// owner. It replaces the former single shared worker + global activeOwner:
// PCM, mute and transcripts never cross an owner boundary because each owner
// has a separate subprocess and an owner-bound transcript sink.
//
// Same-owner behaviour: a second /ws/audio connection from the same owner
// shares that owner's Session (refcounted). Its PCM interleaves only with that
// owner's own other connection, and transcripts fan out to all of that owner's
// /ws clients. When auth is disabled (local dev) every client has the empty
// owner and therefore shares one Session — the single-user default.
//
// SCALE-2 note: this is an in-process, per-replica singleton. A Session is
// pinned to the replica that terminates the owner's WebSockets; running
// numReplicas > 1 requires sticky routing of /ws and /ws/audio to one replica.
type SessionManager struct {
	ctx          context.Context
	pythonBin    string
	scriptPath   string
	workDir      string
	whisperModel string
	maxSessions  int
	route        TranscriptRouter
	log          zerolog.Logger

	mu       sync.Mutex
	sessions map[string]*Session
	stopped  bool
	// V3: owners whose TTS is currently playing, with the time the mute was
	// taken. The browser sends tts_mute once when ARIA starts speaking and
	// tts_unmute once when it stops, so the intent outlives any single worker:
	// if the owner's /ws/audio socket blips mid-speech, the rebuilt session
	// must come up muted rather than forward ARIA's own voice into Whisper.
	//
	// The timestamp bounds THIS RECORD, so a client that vanished mid-sentence
	// cannot make every future session for that owner come up muted. It does
	// not expire a mute already set on a live worker — see mutedOwnerTTL, and
	// TestSessionManager_LiveSessionIsHealedByAnExplicitUnmute, which pins that
	// distinction. A live session is healed by the browser's resync, not by
	// this clock.
	mutedOwners map[string]time.Time
}

// NewSessionManager creates a manager whose sessions are children of ctx.
// maxSessions bounds the number of concurrent distinct-owner subprocesses
// (each loads its own Whisper model); values < 1 mean unbounded.
func NewSessionManager(ctx context.Context, pythonBin, scriptPath, workDir, whisperModel string, maxSessions int, route TranscriptRouter) *SessionManager {
	return &SessionManager{
		ctx:          ctx,
		pythonBin:    pythonBin,
		scriptPath:   scriptPath,
		workDir:      workDir,
		whisperModel: whisperModel,
		maxSessions:  maxSessions,
		route:        route,
		log:          log.With().Str("component", "audio-sessions").Logger(),
		sessions:     make(map[string]*Session),
		mutedOwners:  make(map[string]time.Time),
	}
}

// Acquire registers one more connection for owner, starting the owner's
// worker on first use. Every successful Acquire must be paired with a Release.
// A session that is still draining (its last connection just left) stays in
// the map and counts against the cap; a reconnect for that owner waits for
// the old subprocess to exit before a fresh one is started, so churn can
// never stack subprocesses per owner.
func (m *SessionManager) Acquire(owner string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	for {
		if m.stopped {
			return ErrManagerStopped
		}
		s, ok := m.sessions[owner]
		if !ok {
			break
		}
		if !s.draining {
			s.refs++
			return nil
		}
		m.mu.Unlock()
		<-s.done
		m.mu.Lock()
	}
	if m.maxSessions > 0 && len(m.sessions) >= m.maxSessions {
		return ErrTooManySessions
	}

	ctx, cancel := context.WithCancel(m.ctx)
	sink := func(data []byte) { m.route(owner, data) }
	w := New(m.pythonBin, m.scriptPath, m.workDir, m.whisperModel, sink)
	if m.stillSpeakingLocked(owner, time.Now()) {
		// Still mid-TTS: come up muted so the reconnect cannot leak ARIA's
		// own voice into this owner's pipeline (V3).
		w.Mute(true)
	}
	s := &Session{owner: owner, worker: w, refs: 1, cancel: cancel, done: make(chan struct{})}
	m.sessions[owner] = s

	go func() {
		defer close(s.done)
		if err := w.Start(ctx); err != nil {
			m.log.Error().Err(err).Str("owner", owner).Msg("audio session worker failed")
		}
	}()
	m.log.Info().Str("owner", owner).Msg("audio session started")
	return nil
}

// Release drops one connection for owner. When the last connection goes, the
// owner's worker is shut down and the session removed. It blocks until the
// worker has exited (bounded by the worker's own SIGTERM→SIGKILL delay).
func (m *SessionManager) Release(owner string) {
	m.mu.Lock()
	s, ok := m.sessions[owner]
	if !ok || s.draining {
		m.mu.Unlock()
		return
	}
	s.refs--
	if s.refs > 0 {
		m.mu.Unlock()
		return
	}
	s.draining = true
	m.mu.Unlock()

	m.teardown(s)

	m.mu.Lock()
	if cur, ok := m.sessions[owner]; ok && cur == s {
		delete(m.sessions, owner)
	}
	for o, taken := range m.mutedOwners {
		// Clients come and go here, so this is the natural moment to drop the
		// mutes of owners who left mid-sentence and never came back.
		if time.Since(taken) > mutedOwnerTTL {
			delete(m.mutedOwners, o)
		}
	}
	m.mu.Unlock()
	m.log.Info().Str("owner", owner).Msg("audio session stopped")
}

// teardown ends a session's subprocess: stdin EOF lets the Python loop exit
// on its own, cancel sends SIGTERM (and SIGKILL after WaitDelay), and done
// confirms the restart loop and scanner goroutines have returned.
func (m *SessionManager) teardown(s *Session) {
	s.worker.closeStdin()
	s.cancel()
	<-s.done
}

// WriteAudio forwards one PCM frame to owner's worker. Frames for an owner
// with no live session are dropped: audio is never rerouted to another owner.
func (m *SessionManager) WriteAudio(owner string, pcm []byte) {
	m.mu.Lock()
	s, ok := m.sessions[owner]
	m.mu.Unlock()
	if !ok || s.draining {
		return
	}
	s.worker.WriteAudio(pcm)
}

// SetMuted gates owner's PCM at the edge while that owner's TTS plays. It
// affects only owner's session.
func (m *SessionManager) SetMuted(owner string, muted bool) {
	// The lock is held across worker.Mute so two connections of one owner
	// cannot update the map in one order and reach the worker in the other,
	// leaving the flag and the record disagreeing. Mute is a non-blocking
	// atomic store, so holding the lock costs nothing.
	m.mu.Lock()
	defer m.mu.Unlock()
	if muted {
		m.mutedOwners[owner] = time.Now()
	} else {
		delete(m.mutedOwners, owner)
	}
	s, ok := m.sessions[owner]
	if !ok {
		// No live session yet. The intent is recorded, and Acquire applies it.
		return
	}
	s.worker.Mute(muted)
}

// stillSpeakingLocked reports whether owner holds an unexpired TTS mute, and
// drops the entry when it has aged out. Callers must hold m.mu.
func (m *SessionManager) stillSpeakingLocked(owner string, now time.Time) bool {
	taken, ok := m.mutedOwners[owner]
	if !ok {
		return false
	}
	if now.Sub(taken) > mutedOwnerTTL {
		delete(m.mutedOwners, owner)
		return false
	}
	return true
}

// ageMutedOwner backdates an owner's retained mute. Test-only seam for driving
// TTL expiry without sleeping through it.
func (m *SessionManager) ageMutedOwner(owner string, by time.Duration) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if taken, ok := m.mutedOwners[owner]; ok {
		m.mutedOwners[owner] = taken.Add(-by)
	}
}

// mutedOwnerCount reports how many owners are currently marked as speaking.
// Test-only window proving the set does not grow without bound.
func (m *SessionManager) mutedOwnerCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	return len(m.mutedOwners)
}

// isMutedOwner reports whether owner holds a retained mute. Test-only.
func (m *SessionManager) isMutedOwner(owner string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	_, ok := m.mutedOwners[owner]
	return ok
}

// Running reports whether owner currently has a live subprocess.
func (m *SessionManager) Running(owner string) bool {
	m.mu.Lock()
	s, ok := m.sessions[owner]
	m.mu.Unlock()
	return ok && s.worker.Running()
}

// SessionCount returns the number of distinct owners with a live (non-draining)
// session.
func (m *SessionManager) SessionCount() int {
	m.mu.Lock()
	defer m.mu.Unlock()
	n := 0
	for _, s := range m.sessions {
		if !s.draining {
			n++
		}
	}
	return n
}

// Ready reports whether the manager can spawn sessions: it has not been
// stopped and the worker script exists. Workers are on-demand, so readiness
// no longer waits for a Whisper model load; the first connection pays that.
func (m *SessionManager) Ready() bool {
	m.mu.Lock()
	stopped := m.stopped
	m.mu.Unlock()
	if stopped {
		return false
	}
	_, err := os.Stat(m.scriptPath)
	return err == nil
}

// Stop terminates every session concurrently and refuses further Acquires.
// It satisfies the server's workerStopper for graceful shutdown.
func (m *SessionManager) Stop() {
	m.mu.Lock()
	m.stopped = true
	live := make([]*Session, 0, len(m.sessions))
	for owner, s := range m.sessions {
		live = append(live, s)
		delete(m.sessions, owner)
	}
	m.mu.Unlock()

	var wg sync.WaitGroup
	for _, s := range live {
		wg.Add(1)
		go func(s *Session) {
			defer wg.Done()
			// A draining session is already being torn down by its Release;
			// teardown is idempotent, so this only waits for it to finish.
			m.teardown(s)
		}(s)
	}
	wg.Wait()
}

package server

import (
	"errors"
	"net/http"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/audio"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// maxAudioFrameSize bounds a single inbound audio frame. The browser streams
// ~20-40 ms of 16 kHz mono Int16 PCM (roughly 640-1280 bytes) per frame; the
// generous cap tolerates larger buffered frames while rejecting abusive payloads.
const maxAudioFrameSize = 16384

// audioReadWait is how long an audio socket may stay silent (no frame, no
// pong) before it is closed and its session ref released. Without it a peer
// that vanished without a FIN would pin its owner's session forever and, with
// the session cap, lock other owners out. Immutable in production; tests that
// need a shorter wait call serveAudioWs directly with their own value.
const audioReadWait = pongWait

// ServeAudioWs authenticates and upgrades the connection to the browser mic
// stream at /ws/audio, then forwards each binary PCM frame to the connection
// owner's own audio session.
//
// It uses the same auth as ServeWs: a valid Clerk session token carried as the
// non-marker entry of the Sec-WebSocket-Protocol header (SEC-1) — a query-string
// token is never read. The authenticated owner is bound to this connection for
// its whole life: every frame is written to that owner's session and released
// from it on disconnect. No global routing state exists for another connection
// to seize (SEC-6). When auth is disabled (local dev) the owner is empty and
// all local clients share the empty-owner session. Only binary frames are
// forwarded; text frames are ignored.
func ServeAudioWs(hub *Hub, verifier auth.Verifier, authEnabled bool, allowedOrigins []string, w http.ResponseWriter, r *http.Request) {
	serveAudioWs(hub, verifier, authEnabled, allowedOrigins, audioReadWait, w, r)
}

// serveAudioWs is ServeAudioWs with the silent-socket read wait as a parameter.
// Production always passes audioReadWait; tests pass a short value so the
// reaper can be exercised without mutating any state shared across handlers.
func serveAudioWs(hub *Hub, verifier auth.Verifier, authEnabled bool, allowedOrigins []string, readWait time.Duration, w http.ResponseWriter, r *http.Request) {
	owner := ""
	if authEnabled {
		token := tokenFromSubprotocols(websocket.Subprotocols(r))
		if token == "" {
			writeWSUnauthorized(w)
			return
		}
		verified, err := verifier.Verify(r.Context(), token)
		if err != nil || verified == "" {
			writeWSUnauthorized(w)
			return
		}
		owner = verified
	}

	upgrader := newUpgrader(allowedOrigins)
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Error().Err(err).Msg("audio websocket upgrade failed")
		return
	}
	defer conn.Close()

	conn.SetReadLimit(maxAudioFrameSize)
	conn.SetReadDeadline(time.Now().Add(readWait)) //nolint:errcheck
	conn.SetPongHandler(func(string) error {
		return conn.SetReadDeadline(time.Now().Add(readWait))
	})
	stopPing := startAudioPing(conn, readWait)
	defer stopPing()

	// AUDIO_ENABLED=false wires no controller: keep the socket open and drop
	// frames silently (documented behaviour) instead of closing, which would
	// put the browser into its reconnect loop.
	if hub.audio == nil {
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
			conn.SetReadDeadline(time.Now().Add(readWait)) //nolint:errcheck
		}
	}
	if err := hub.audio.Acquire(owner); err != nil {
		code := websocket.CloseInternalServerErr
		if errors.Is(err, audio.ErrTooManySessions) {
			code = websocket.CloseTryAgainLater
		}
		log.Warn().Err(err).Msg("audio session refused")
		_ = conn.WriteControl(
			websocket.CloseMessage,
			websocket.FormatCloseMessage(code, "audio session unavailable"),
			time.Now().Add(writeWait),
		)
		return
	}
	defer hub.audio.Release(owner)

	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Warn().Err(err).Msg("unexpected audio websocket close")
			}
			return
		}
		conn.SetReadDeadline(time.Now().Add(readWait)) //nolint:errcheck
		if msgType != websocket.BinaryMessage {
			continue
		}
		hub.audio.WriteAudio(owner, data)
	}
}

// startAudioPing pings the audio socket periodically so a live browser keeps
// refreshing the read deadline via pongs. The returned func stops the ticker.
// The audio socket has no other writer, so no write mutex is needed.
func startAudioPing(conn *websocket.Conn, readWait time.Duration) func() {
	period := readWait * 9 / 10
	if period <= 0 {
		period = readWait
	}
	ticker := time.NewTicker(period)
	done := make(chan struct{})
	go func() {
		for {
			select {
			case <-ticker.C:
				if err := conn.WriteControl(websocket.PingMessage, nil, time.Now().Add(writeWait)); err != nil {
					return
				}
			case <-done:
				return
			}
		}
	}()
	return func() {
		ticker.Stop()
		close(done)
	}
}

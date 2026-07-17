package server

import (
	"net/http"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// maxAudioFrameSize bounds a single inbound audio frame. The browser streams
// ~20-40 ms of 16 kHz mono Int16 PCM (roughly 640-1280 bytes) per frame; the
// generous cap tolerates larger buffered frames while rejecting abusive payloads.
const maxAudioFrameSize = 16384

// ServeAudioWs authenticates and upgrades the connection to the browser mic
// stream at /ws/audio, then forwards each binary PCM frame to the audio worker.
//
// It uses the same auth as ServeWs: a valid Clerk session token carried as the
// non-marker entry of the Sec-WebSocket-Protocol header (SEC-1) — a query-string
// token is never read. The authenticated owner claims the local perception
// stream so transcripts derived from this mic are scoped to that owner. When auth
// is disabled (local dev) the owner is empty and transcripts fall back to all
// clients. Only binary frames are forwarded; text frames are ignored.
func ServeAudioWs(hub *Hub, verifier auth.Verifier, authEnabled bool, allowedOrigins []string, w http.ResponseWriter, r *http.Request) {
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

	hub.setActiveOwner(owner)

	conn.SetReadLimit(maxAudioFrameSize)
	for {
		msgType, data, err := conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Warn().Err(err).Msg("unexpected audio websocket close")
			}
			return
		}
		if msgType != websocket.BinaryMessage {
			continue
		}
		if hub.audio != nil {
			hub.audio.WriteAudio(data)
		}
	}
}

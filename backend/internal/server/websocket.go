package server

import (
	"net/http"
	"strings"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// originAllowed reports whether a WebSocket handshake Origin is permitted.
// A missing Origin (non-browser client) is allowed; a browser Origin must be
// present in the configured allow-list.
func originAllowed(origin string, allowed []string) bool {
	if origin == "" {
		return true
	}
	for _, a := range allowed {
		if strings.EqualFold(origin, a) {
			return true
		}
	}
	return false
}

// wsSubprotocol is the fixed marker subprotocol the client sends alongside the
// Clerk session token (as `["aria-ws", token]`). The server negotiates and
// echoes back only this marker so the browser accepts the handshake; the token
// is never echoed.
const wsSubprotocol = "aria-ws"

func newUpgrader(allowedOrigins []string) websocket.Upgrader {
	return websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 4096,
		Subprotocols:    []string{wsSubprotocol},
		CheckOrigin: func(r *http.Request) bool {
			return originAllowed(r.Header.Get("Origin"), allowedOrigins)
		},
	}
}

// tokenFromSubprotocols returns the auth token offered in the client's
// Sec-WebSocket-Protocol header: the first entry that is not the marker
// subprotocol. It returns "" when only the marker (or nothing) is present.
func tokenFromSubprotocols(protocols []string) string {
	for _, p := range protocols {
		if p != wsSubprotocol {
			return p
		}
	}
	return ""
}

// ServeWs authenticates and upgrades the HTTP connection to a WebSocket, then
// registers the client with the hub.
//
// When authEnabled is true it requires a valid Clerk session token carried in
// the `Sec-WebSocket-Protocol` request header (as the non-marker entry of
// `aria-ws, <token>`) — browsers cannot set the Authorization header on a
// WebSocket handshake, and a query-string token would leak into logs/history
// (SEC-1). It rejects a missing/invalid token with HTTP 401. When authEnabled
// is false (local dev, no Clerk secret), token verification is skipped and the
// client's owner is empty.
func ServeWs(hub *Hub, verifier auth.Verifier, authEnabled bool, allowedOrigins []string, w http.ResponseWriter, r *http.Request) {
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
		log.Error().Err(err).Msg("websocket upgrade failed")
		return
	}

	client := &Client{
		hub:   hub,
		conn:  conn,
		send:  make(chan []byte, 256),
		owner: owner,
	}

	hub.register <- client

	go client.writePump()
	go client.readPump()
}

func writeWSUnauthorized(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusUnauthorized)
	w.Write([]byte(`{"error":"unauthorized"}`)) //nolint:errcheck
}

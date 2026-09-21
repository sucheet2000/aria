package server

import (
	"context"
	"encoding/json"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
	"github.com/rs/zerolog/log"
)

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = 54 * time.Second
	maxMessageSize = 65536
)

// AudioController is the owner-keyed audio session surface the edge drives.
// Every call carries the owner from the authenticated connection, never a
// client-supplied field, so one owner's PCM, mute or lifecycle can never
// touch another owner's session (SEC-6). Implemented by audio.SessionManager.
type AudioController interface {
	Acquire(owner string) error
	Release(owner string)
	WriteAudio(owner string, pcm []byte)
	// SetMuted records or clears ONE connection's TTS mute hold. The owner is
	// muted while any of its connections holds, so a tab that finished
	// speaking cannot un-gate a sibling that is still talking.
	SetMuted(owner, holder string, muted bool)
	// ReleaseMuteHolder drops one connection's hold when that connection goes
	// away and can no longer release it itself.
	ReleaseMuteHolder(owner, holder string)
}

// broadcastMsg is a queued broadcast. When scoped is true the message is only
// delivered to clients whose owner equals owner; otherwise it goes to all.
type broadcastMsg struct {
	data   []byte
	owner  string
	scoped bool
}

// Hub maintains the set of active clients and broadcasts messages to them.
type Hub struct {
	clients    map[*Client]bool
	broadcast  chan broadcastMsg
	register   chan *Client
	unregister chan *Client
	mu         sync.RWMutex
	audio      AudioController
}

// Client represents a single WebSocket connection.
type Client struct {
	hub   *Hub
	conn  *websocket.Conn
	send  chan []byte
	owner string
	// id distinguishes this connection from the owner's other tabs, so a TTS
	// mute hold belongs to one connection rather than to the account.
	id string
}

// nextClientID hands out a unique id per accepted connection. Only uniqueness
// within the process matters; it never leaves the server.
var nextClientID atomic.Uint64

func newClientID() string {
	return strconv.FormatUint(nextClientID.Add(1), 10)
}

// NewHub creates and returns a new Hub.
func NewHub() *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		broadcast:  make(chan broadcastMsg, 2048),
		register:   make(chan *Client),
		unregister: make(chan *Client),
	}
}

// SetAudio wires an AudioController into the hub.
// Must be called before Run.
func (h *Hub) SetAudio(a AudioController) {
	h.audio = a
}

// Run processes hub events: register, unregister, and broadcast.
func (h *Hub) Run(_ context.Context) {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client] = true
			h.mu.Unlock()
			log.Info().Str("remote", client.conn.RemoteAddr().String()).Msg("client connected")

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
			h.mu.Unlock()
			log.Info().Str("remote", client.conn.RemoteAddr().String()).Msg("client disconnected")

		case bm := <-h.broadcast:
			h.mu.RLock()
			for client := range h.clients {
				if bm.scoped && client.owner != bm.owner {
					continue
				}
				select {
				case client.send <- bm.data:
				default:
					// Buffer full: skip this message for this client instead
					// of dropping them. Prevents the 1s reconnect gap that
					// causes missed transcripts.
				}
			}
			h.mu.RUnlock()
		}
	}
}

// Broadcast sends a message to all connected clients.
func (h *Hub) Broadcast(msg []byte) {
	h.broadcast <- broadcastMsg{data: msg}
}

// BroadcastToOwner sends a message only to clients whose owner matches. It is
// the transcript route for the audio session manager: a transcript produced
// by owner A's worker is delivered to A's /ws clients and nobody else. When
// auth is disabled every client has the empty owner, so the empty owner
// reaches all local clients — the single-user default.
func (h *Hub) BroadcastToOwner(owner string, msg []byte) {
	h.broadcast <- broadcastMsg{data: msg, owner: owner, scoped: true}
}

// writePump pumps messages from the hub to the WebSocket connection.
func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := c.conn.WriteMessage(websocket.TextMessage, message); err != nil {
				log.Warn().Err(err).Msg("write error, dropping client")
				return
			}

		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

// readPump reads from the WebSocket to detect disconnects and sets read deadlines.
// Control messages (tts_mute/tts_unmute) act only on the sending connection's
// authenticated owner; any owner-like field in the payload is ignored.
func (c *Client) readPump() {
	defer func() {
		// This connection can no longer send tts_unmute, so drop its hold and
		// only its hold. A sibling tab that is still speaking keeps the owner
		// muted; the page that owned this hold is gone, and the browser's own
		// local gate covers a page that is merely reconnecting.
		if c.hub.audio != nil {
			c.hub.audio.ReleaseMuteHolder(c.owner, c.id)
		}
		c.hub.unregister <- c
		c.conn.Close()
	}()

	c.conn.SetReadLimit(maxMessageSize)
	c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, message, err := c.conn.ReadMessage()
		var msg struct {
			Type string `json:"type"`
		}
		if json.Unmarshal(message, &msg) == nil {
			switch msg.Type {
			case "tts_mute":
				if c.hub.audio != nil {
					c.hub.audio.SetMuted(c.owner, c.id, true)
				}
			case "tts_unmute":
				if c.hub.audio != nil {
					c.hub.audio.SetMuted(c.owner, c.id, false)
				}
			}
		}
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Warn().Err(err).Msg("unexpected websocket close")
			}
			break
		}
	}
}

package server

import (
	"context"
	"sync"
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

// VisionController is implemented by the vision worker.
type VisionController interface {
	Start(ctx context.Context) error
	Stop()
}

// Hub maintains the set of active clients and broadcasts messages to them.
type Hub struct {
	clients    map[*Client]bool
	broadcast  chan []byte
	register   chan *Client
	unregister chan *Client
	mu         sync.RWMutex
	vision     VisionController
	ctx        context.Context
}

// Client represents a single WebSocket connection.
type Client struct {
	hub  *Hub
	conn *websocket.Conn
	send chan []byte
}

// NewHub creates and returns a new Hub.
func NewHub(v VisionController) *Hub {
	return &Hub{
		clients:    make(map[*Client]bool),
		broadcast:  make(chan []byte, 2048),
		register:   make(chan *Client),
		unregister: make(chan *Client),
		vision:     v,
	}
}

// SetVision wires a VisionController into a hub that was created with nil.
// Must be called before Run.
func (h *Hub) SetVision(v VisionController) {
	h.vision = v
}

// Run processes hub events: register, unregister, and broadcast.
func (h *Hub) Run(ctx context.Context) {
	h.ctx = ctx
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			wasEmpty := len(h.clients) == 0
			h.clients[client] = true
			h.mu.Unlock()
			log.Info().Str("remote", client.conn.RemoteAddr().String()).Msg("client connected")
			if wasEmpty && h.vision != nil {
				go func() {
					if err := h.vision.Start(h.ctx); err != nil {
						log.Error().Err(err).Msg("vision worker exited with error")
					}
				}()
			}

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client]; ok {
				delete(h.clients, client)
				close(client.send)
			}
			nowEmpty := len(h.clients) == 0
			h.mu.Unlock()
			log.Info().Str("remote", client.conn.RemoteAddr().String()).Msg("client disconnected")
			if nowEmpty && h.vision != nil {
				go func() {
					time.Sleep(3000 * time.Millisecond)
					h.mu.RLock()
					stillEmpty := len(h.clients) == 0
					h.mu.RUnlock()
					if stillEmpty {
						h.vision.Stop()
					}
				}()
			}

		case message := <-h.broadcast:
			h.mu.Lock()
			for client := range h.clients {
				select {
				case client.send <- message:
				default:
					// slow client: drop and remove
					close(client.send)
					delete(h.clients, client)
				}
			}
			h.mu.Unlock()
		}
	}
}

// Broadcast sends a message to all connected clients.
func (h *Hub) Broadcast(msg []byte) {
	h.broadcast <- msg
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
func (c *Client) readPump() {
	defer func() {
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
		_, _, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Warn().Err(err).Msg("unexpected websocket close")
			}
			break
		}
	}
}

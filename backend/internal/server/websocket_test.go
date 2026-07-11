package server

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

type fakeTokenVerifier struct {
	owner string
	err   error
}

func (f fakeTokenVerifier) Verify(_ context.Context, _ string) (string, error) {
	return f.owner, f.err
}

var testOrigins = []string{"http://localhost:3000", "http://127.0.0.1:3000"}

func startWSServer(t *testing.T, verifier auth.Verifier, authEnabled bool, origins []string) (*httptest.Server, *Hub) {
	t.Helper()
	hub := NewHub(nil)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ServeWs(hub, verifier, authEnabled, origins, w, r)
	}))
	t.Cleanup(srv.Close)
	return srv, hub
}

func dialWS(t *testing.T, base, query, origin string, subprotocols ...string) (*websocket.Conn, *http.Response, error) {
	t.Helper()
	u := "ws" + strings.TrimPrefix(base, "http") + "/ws"
	if query != "" {
		u += "?" + query
	}
	header := http.Header{}
	if origin != "" {
		header.Set("Origin", origin)
	}
	dialer := *websocket.DefaultDialer
	dialer.Subprotocols = subprotocols
	return dialer.Dial(u, header)
}

func statusOf(resp *http.Response) int {
	if resp == nil {
		return -1
	}
	return resp.StatusCode
}

func waitForClients(t *testing.T, hub *Hub, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		hub.mu.RLock()
		n := len(hub.clients)
		hub.mu.RUnlock()
		if n >= want {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %d clients", want)
}

func TestServeWs_AuthEnabled_MissingToken_401(t *testing.T) {
	srv, _ := startWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "", "http://localhost:3000")
	if conn != nil {
		conn.Close()
	}
	if err == nil {
		t.Fatal("expected handshake to fail with no token")
	}
	if statusOf(resp) != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", statusOf(resp))
	}
}

func TestServeWs_AuthEnabled_InvalidToken_401(t *testing.T) {
	srv, _ := startWSServer(t, fakeTokenVerifier{err: errors.New("bad token")}, true, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "", "http://localhost:3000", wsSubprotocol, "bad")
	if conn != nil {
		conn.Close()
	}
	if err == nil {
		t.Fatal("expected handshake to fail with invalid token")
	}
	if statusOf(resp) != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", statusOf(resp))
	}
}

// TestServeWs_AuthEnabled_QueryToken_NotAuthenticated proves SEC-1: a token in
// the URL query string is no longer read, so it must NOT authenticate.
func TestServeWs_AuthEnabled_QueryToken_NotAuthenticated(t *testing.T) {
	srv, _ := startWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "token=good", "http://localhost:3000")
	if conn != nil {
		conn.Close()
	}
	if err == nil {
		t.Fatal("expected handshake to fail: query-string token must not authenticate")
	}
	if statusOf(resp) != http.StatusUnauthorized {
		t.Fatalf("status = %d, want 401", statusOf(resp))
	}
}

func TestServeWs_AuthEnabled_ValidToken_AcceptedAndOwnerScoped(t *testing.T) {
	srv, hub := startWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "", "http://localhost:3000", wsSubprotocol, "good")
	if err != nil {
		t.Fatalf("dial failed: %v (status %d)", err, statusOf(resp))
	}
	defer conn.Close()
	if statusOf(resp) != http.StatusSwitchingProtocols {
		t.Fatalf("status = %d, want 101", statusOf(resp))
	}

	// The server MUST echo back the marker subprotocol (and only the marker,
	// never the token) or the browser aborts the connection.
	if got := resp.Header.Get("Sec-Websocket-Protocol"); got != wsSubprotocol {
		t.Fatalf("response Sec-WebSocket-Protocol = %q, want %q", got, wsSubprotocol)
	}
	if got := conn.Subprotocol(); got != wsSubprotocol {
		t.Fatalf("negotiated subprotocol = %q, want %q", got, wsSubprotocol)
	}

	waitForClients(t, hub, 1)

	// A broadcast scoped to this owner must arrive.
	hub.BroadcastToOwner("user_a", []byte(`{"type":"mine"}`))
	conn.SetReadDeadline(time.Now().Add(2 * time.Second))
	_, msg, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("expected owner-scoped message, read error: %v", err)
	}
	if string(msg) != `{"type":"mine"}` {
		t.Fatalf("message = %q, want scoped payload", msg)
	}

	// A broadcast for a DIFFERENT owner must NOT arrive.
	hub.BroadcastToOwner("user_b", []byte(`{"type":"leak"}`))
	conn.SetReadDeadline(time.Now().Add(300 * time.Millisecond))
	if _, leaked, err := conn.ReadMessage(); err == nil {
		t.Fatalf("client received message meant for another owner: %q", leaked)
	}
}

func TestServeWs_DisallowedOrigin_Rejected(t *testing.T) {
	srv, _ := startWSServer(t, nil, false, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "", "http://evil.example.com")
	if conn != nil {
		conn.Close()
	}
	if err == nil {
		t.Fatal("expected handshake rejection for disallowed origin")
	}
	if statusOf(resp) != http.StatusForbidden {
		t.Fatalf("status = %d, want 403", statusOf(resp))
	}
}

func TestServeWs_AllowedOrigin_AuthDisabled_Accepted(t *testing.T) {
	srv, hub := startWSServer(t, nil, false, testOrigins)

	conn, resp, err := dialWS(t, srv.URL, "", "http://127.0.0.1:3000")
	if err != nil {
		t.Fatalf("dial failed: %v (status %d)", err, statusOf(resp))
	}
	defer conn.Close()
	if statusOf(resp) != http.StatusSwitchingProtocols {
		t.Fatalf("status = %d, want 101", statusOf(resp))
	}
	waitForClients(t, hub, 1)
}

func TestOriginAllowed(t *testing.T) {
	allowed := []string{"http://localhost:3000", "http://127.0.0.1:3000"}
	cases := []struct {
		origin string
		want   bool
	}{
		{"", true},
		{"http://localhost:3000", true},
		{"http://127.0.0.1:3000", true},
		{"http://evil.com", false},
		{"https://localhost:3000", false},
	}
	for _, c := range cases {
		if got := originAllowed(c.origin, allowed); got != c.want {
			t.Errorf("originAllowed(%q) = %v, want %v", c.origin, got, c.want)
		}
	}
}

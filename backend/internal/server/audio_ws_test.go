package server

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/gorilla/websocket"
	"github.com/sucheet2000/aria/backend/internal/auth"
)

// recordingAudio is a fake owner-keyed AudioController that records forwarded
// PCM frames, satisfying the hub's AudioController interface.
type recordingAudio struct {
	mu     sync.Mutex
	frames [][]byte
}

func (r *recordingAudio) Acquire(_ string) error { return nil }

func (r *recordingAudio) Release(_ string) {}

func (r *recordingAudio) WriteAudio(_ string, pcm []byte) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.frames = append(r.frames, append([]byte(nil), pcm...))
}

func (r *recordingAudio) SetMuted(_, _ string, _ bool) {}

func (r *recordingAudio) ReleaseMuteHolder(_, _ string) {}

func (r *recordingAudio) frameCount() int {
	r.mu.Lock()
	defer r.mu.Unlock()
	return len(r.frames)
}

func (r *recordingAudio) firstFrame() []byte {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.frames) == 0 {
		return nil
	}
	return append([]byte(nil), r.frames[0]...)
}

func startAudioWSServer(t *testing.T, verifier auth.Verifier, authEnabled bool, origins []string) (*httptest.Server, *recordingAudio) {
	t.Helper()
	hub := NewHub()
	audio := &recordingAudio{}
	hub.SetAudio(audio)
	ctx, cancel := context.WithCancel(context.Background())
	t.Cleanup(cancel)
	go hub.Run(ctx)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ServeAudioWs(hub, verifier, authEnabled, origins, w, r)
	}))
	t.Cleanup(srv.Close)
	return srv, audio
}

func dialAudioWS(t *testing.T, base, query, origin string, subprotocols ...string) (*websocket.Conn, *http.Response, error) {
	t.Helper()
	u := "ws" + strings.TrimPrefix(base, "http") + "/ws/audio"
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

func waitForFrames(t *testing.T, audio *recordingAudio, want int) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if audio.frameCount() >= want {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %d forwarded frames, got %d", want, audio.frameCount())
}

func TestServeAudioWs_AuthEnabled_MissingToken_401(t *testing.T) {
	srv, _ := startAudioWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://localhost:3000")
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

func TestServeAudioWs_AuthEnabled_InvalidToken_401(t *testing.T) {
	srv, _ := startAudioWSServer(t, fakeTokenVerifier{err: errors.New("bad token")}, true, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://localhost:3000", wsSubprotocol, "bad")
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

// TestServeAudioWs_AuthEnabled_QueryToken_NotAuthenticated proves SEC-1 on the
// audio socket: a token in the URL query string must NOT authenticate.
func TestServeAudioWs_AuthEnabled_QueryToken_NotAuthenticated(t *testing.T) {
	srv, _ := startAudioWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "token=good", "http://localhost:3000")
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

func TestServeAudioWs_ValidToken_ForwardsBinaryFrame(t *testing.T) {
	srv, audio := startAudioWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://localhost:3000", wsSubprotocol, "good")
	if err != nil {
		t.Fatalf("dial failed: %v (status %d)", err, statusOf(resp))
	}
	defer conn.Close()
	if statusOf(resp) != http.StatusSwitchingProtocols {
		t.Fatalf("status = %d, want 101", statusOf(resp))
	}

	frame := []byte{0x01, 0x02, 0x03, 0x04}
	if err := conn.WriteMessage(websocket.BinaryMessage, frame); err != nil {
		t.Fatalf("write binary frame: %v", err)
	}

	waitForFrames(t, audio, 1)
	if got := audio.firstFrame(); !bytes.Equal(got, frame) {
		t.Fatalf("forwarded frame = %v, want %v", got, frame)
	}
}

// TestServeAudioWs_TextFrame_NotForwarded proves only binary PCM frames drive the
// STT pipeline; text frames are ignored.
func TestServeAudioWs_TextFrame_NotForwarded(t *testing.T) {
	srv, audio := startAudioWSServer(t, fakeTokenVerifier{owner: "user_a"}, true, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://localhost:3000", wsSubprotocol, "good")
	if err != nil {
		t.Fatalf("dial failed: %v (status %d)", err, statusOf(resp))
	}
	defer conn.Close()

	if err := conn.WriteMessage(websocket.TextMessage, []byte("hello")); err != nil {
		t.Fatalf("write text frame: %v", err)
	}
	// Then a binary frame, which MUST be forwarded — proving the text one was skipped.
	if err := conn.WriteMessage(websocket.BinaryMessage, []byte{0x09}); err != nil {
		t.Fatalf("write binary frame: %v", err)
	}

	waitForFrames(t, audio, 1)
	if n := audio.frameCount(); n != 1 {
		t.Fatalf("forwarded frame count = %d, want 1 (text frame must be ignored)", n)
	}
}

func TestServeAudioWs_AuthDisabled_AllowedOrigin_Forwards(t *testing.T) {
	srv, audio := startAudioWSServer(t, nil, false, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://127.0.0.1:3000")
	if err != nil {
		t.Fatalf("dial failed: %v (status %d)", err, statusOf(resp))
	}
	defer conn.Close()
	if statusOf(resp) != http.StatusSwitchingProtocols {
		t.Fatalf("status = %d, want 101", statusOf(resp))
	}

	if err := conn.WriteMessage(websocket.BinaryMessage, []byte{0x07, 0x08}); err != nil {
		t.Fatalf("write binary frame: %v", err)
	}
	waitForFrames(t, audio, 1)
}

func TestServeAudioWs_DisallowedOrigin_Rejected(t *testing.T) {
	srv, _ := startAudioWSServer(t, nil, false, testOrigins)

	conn, resp, err := dialAudioWS(t, srv.URL, "", "http://evil.example.com")
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

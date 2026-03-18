package tts

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestNewClient(t *testing.T) {
	c := New("test-key", "test-voice")
	if c.apiKey != "test-key" {
		t.Errorf("expected apiKey 'test-key', got %q", c.apiKey)
	}
	if c.voiceID != "test-voice" {
		t.Errorf("expected voiceID 'test-voice', got %q", c.voiceID)
	}
	if c.httpClient == nil {
		t.Error("expected non-nil httpClient")
	}
}

func TestStreamEmptyAPIKeyDoesNotPanic(t *testing.T) {
	c := New("", "")
	var buf bytes.Buffer
	// The say command may not exist in all CI environments, so we only check it
	// does not panic. An error is acceptable.
	_ = c.Stream(context.Background(), "hello", &buf)
}

func TestTTSRequestJSONMarshal(t *testing.T) {
	req := TTSRequest{
		Text:    "hello world",
		VoiceID: "abc123",
	}
	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}

	var out TTSRequest
	if err := json.Unmarshal(data, &out); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if out.Text != req.Text {
		t.Errorf("expected text %q, got %q", req.Text, out.Text)
	}
	if out.VoiceID != req.VoiceID {
		t.Errorf("expected voice_id %q, got %q", req.VoiceID, out.VoiceID)
	}
}

func TestTTSRequestJSONOmitsEmptyVoiceID(t *testing.T) {
	req := TTSRequest{Text: "hello"}
	data, err := json.Marshal(req)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if _, ok := m["voice_id"]; ok {
		t.Error("expected voice_id to be omitted when empty")
	}
}

func TestHandlerRejects405ForGET(t *testing.T) {
	h := NewHandler(New("", ""))
	req := httptest.NewRequest(http.MethodGet, "/api/tts", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("expected 405, got %d", rec.Code)
	}
}

func TestHandlerRejects400ForEmptyText(t *testing.T) {
	h := NewHandler(New("", ""))
	body := bytes.NewBufferString(`{"text":""}`)
	req := httptest.NewRequest(http.MethodPost, "/api/tts", body)
	req.Header.Set("Content-Type", "application/json")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusBadRequest {
		t.Errorf("expected 400, got %d", rec.Code)
	}
}

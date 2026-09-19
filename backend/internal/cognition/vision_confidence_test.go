package cognition

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// R2: the browser's heuristic facial-affect confidence must cross the Go edge
// unchanged — never computed, defaulted or clamped here.

func f64(v float64) *float64 { return &v }

func TestCognitionRequest_EmotionConfidenceDecoded(t *testing.T) {
	var req CognitionRequest
	body := `{"message":"hi","session_id":"s","vision_state":{"emotion":"happy","emotion_confidence":0.83}}`
	if err := json.Unmarshal([]byte(body), &req); err != nil {
		t.Fatal(err)
	}
	if req.VisionState.Emotion != "happy" {
		t.Errorf("emotion = %q, want happy", req.VisionState.Emotion)
	}
	if req.VisionState.EmotionConfidence == nil || *req.VisionState.EmotionConfidence != 0.83 {
		t.Errorf("emotion_confidence = %v, want 0.83", req.VisionState.EmotionConfidence)
	}
}

func TestCognitionRequest_EmotionConfidenceAbsentIsNil(t *testing.T) {
	var req CognitionRequest
	if err := json.Unmarshal([]byte(`{"message":"hi","session_id":"s","vision_state":{"emotion":"happy"}}`), &req); err != nil {
		t.Fatal(err)
	}
	if req.VisionState.EmotionConfidence != nil {
		t.Errorf("absent emotion_confidence decoded as %v, want nil", *req.VisionState.EmotionConfidence)
	}
}

// Test 4: Python receives exactly what the browser sent.
func TestClientComplete_PreservesEmotionConfidence(t *testing.T) {
	cases := []struct {
		name     string
		conf     *float64
		wantJSON string // substring of the vision_state object Python receives
	}{
		{"value", f64(0.83), `"emotion_confidence":0.83`},
		{"zero", f64(0), `"emotion_confidence":0`},
		{"distinctive", f64(0.731), `"emotion_confidence":0.731`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			var got map[string]json.RawMessage
			var raw string
			fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body map[string]json.RawMessage
				_ = json.NewDecoder(r.Body).Decode(&body)
				_ = json.Unmarshal(body["vision_state"], &got)
				raw = string(body["vision_state"])
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
			}))
			defer fake.Close()

			c := New(fake.URL, memory.New(5))
			req := CognitionRequest{Message: "m", SessionID: "s1", VisionState: PerceptionFrame{Emotion: "happy", EmotionConfidence: tc.conf, FaceDetected: true}}
			if _, err := c.Complete(auth.WithOwner(context.Background(), "o"), req); err != nil {
				t.Fatal(err)
			}
			if string(got["emotion"]) != `"happy"` {
				t.Errorf("emotion forwarded as %s, want \"happy\"", got["emotion"])
			}
			if !strings.Contains(raw, tc.wantJSON) {
				t.Errorf("vision_state %s does not contain %s", raw, tc.wantJSON)
			}
		})
	}
}

func TestClientComplete_AbsentEmotionConfidenceStaysAbsent(t *testing.T) {
	var raw string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]json.RawMessage
		_ = json.NewDecoder(r.Body).Decode(&body)
		raw = string(body["vision_state"])
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	req := CognitionRequest{Message: "m", SessionID: "s1", VisionState: PerceptionFrame{Emotion: "neutral"}}
	if _, err := c.Complete(context.Background(), req); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(raw, "emotion_confidence") {
		t.Errorf("Go invented an emotion_confidence for a request that had none: %s", raw)
	}
	if strings.Contains(raw, `"confidence"`) {
		t.Errorf("legacy confidence field still emitted: %s", raw)
	}
}

// The edge rejects out-of-range values with 400 instead of turning Python's
// 422 into an opaque 500; in-range values pass through untouched.
func TestHandler_EmotionConfidenceRange(t *testing.T) {
	var forwarded []string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]json.RawMessage
		_ = json.NewDecoder(r.Body).Decode(&body)
		forwarded = append(forwarded, string(body["vision_state"]))
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()
	h := NewHandler(New(fake.URL, memory.New(5)), zerolog.Nop())

	post := func(vs string) int {
		rec := httptest.NewRecorder()
		body := `{"message":"hi","session_id":"s","vision_state":` + vs + `}`
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/cognition", strings.NewReader(body)))
		return rec.Code
	}

	for _, bad := range []string{`{"emotion":"happy","emotion_confidence":-0.1}`, `{"emotion":"happy","emotion_confidence":1.1}`} {
		if code := post(bad); code != http.StatusBadRequest {
			t.Errorf("%s: status %d, want 400", bad, code)
		}
	}
	if len(forwarded) != 0 {
		t.Fatalf("out-of-range confidence was forwarded to Python: %v", forwarded)
	}
	for _, ok := range []string{`{"emotion":"happy","emotion_confidence":0}`, `{"emotion":"happy","emotion_confidence":1}`, `{"emotion":"happy","emotion_confidence":0.5}`, `{"emotion":"happy"}`} {
		if code := post(ok); code != http.StatusOK {
			t.Errorf("%s: status %d, want 200", ok, code)
		}
	}
	if len(forwarded) != 4 {
		t.Fatalf("expected 4 forwarded requests, got %d", len(forwarded))
	}
	if !strings.Contains(forwarded[2], `"emotion_confidence":0.5`) {
		t.Errorf("0.5 not forwarded unchanged: %s", forwarded[2])
	}
	if strings.Contains(forwarded[3], "emotion_confidence") {
		t.Errorf("absent confidence gained a value at the edge: %s", forwarded[3])
	}
}

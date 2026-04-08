package cognition

import (
	"strings"
	"testing"
)

func TestBuildSystemPrompt_FaceDetected_HappyEmotion(t *testing.T) {
	vs := PerceptionFrame{
		Emotion:      "happy",
		FaceDetected: true,
	}
	prompt := BuildSystemPrompt(vs)

	if !strings.Contains(prompt, "ARIA") {
		t.Error("expected prompt to contain ARIA")
	}
	if !strings.Contains(prompt, "happy") {
		t.Error("expected prompt to contain the emotion 'happy'")
	}
	if strings.Contains(prompt, "Claude") {
		t.Error("prompt must not contain 'Claude'")
	}
	if strings.Contains(prompt, "Anthropic") {
		t.Error("prompt must not contain 'Anthropic'")
	}
	// Detect common emoji by looking for non-ASCII characters outside basic Latin range.
	for _, r := range prompt {
		if r > 127 {
			t.Errorf("prompt must not contain emoji or non-ASCII characters, found rune %U", r)
		}
	}
}

func TestBuildSystemPrompt_NoFaceDetected(t *testing.T) {
	vs := PerceptionFrame{
		FaceDetected: false,
	}
	prompt := BuildSystemPrompt(vs)

	lower := strings.ToLower(prompt)
	if !strings.Contains(lower, "stepped away") && !strings.Contains(lower, "not in frame") && !strings.Contains(lower, "absence") {
		t.Error("expected prompt to mention that the user may have stepped away")
	}
}

func TestSuggestEmotion(t *testing.T) {
	cases := []struct {
		input    string
		expected string
	}{
		{"I am so glad to hear that", "happy"},
		{"That is really interesting, I wonder", "thoughtful"},
		{"I am sorry to hear that", "sad"},
		{"hello there", "neutral"},
	}

	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			got := SuggestEmotion(tc.input)
			if got != tc.expected {
				t.Errorf("SuggestEmotion(%q) = %q, want %q", tc.input, got, tc.expected)
			}
		})
	}
}

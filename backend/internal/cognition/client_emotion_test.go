package cognition

import "testing"

// TestSuggestAvatarEmotion covers all seven canonical avatar emotions plus the
// neutral default (see emotion.py: neutral/happy/sad/angry/surprised/fearful/
// disgusted). frustrated is the existing pre-mapping label kept for regression.
func TestSuggestAvatarEmotion(t *testing.T) {
	cases := []struct {
		name     string
		input    string
		expected string
	}{
		{"frustrated", "user is blocked and frustrated", "frustrated"},
		{"fearful", "user seems distressed and worried", "fearful"},
		{"sad", "user is sad and disappointed", "sad"},
		{"angry", "user is angry and furious", "angry"},
		{"disgusted", "user is disgusted and repulsed", "disgusted"},
		{"happy", "user is happy and excited", "happy"},
		{"surprised", "user is confused and lost", "surprised"},
		{"neutral default", "user greeted me warmly", "neutral"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := suggestAvatarEmotion(tc.input)
			if got != tc.expected {
				t.Errorf("suggestAvatarEmotion(%q) = %q, want %q", tc.input, got, tc.expected)
			}
		})
	}
}

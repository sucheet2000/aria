package tts

import (
	"strings"
	"testing"
	"unicode/utf8"
)

// Workstream I — truncating by byte count can cut a multi-byte rune in half,
// putting invalid UTF-8 on the wire. The provider may reject it, or the user
// hears a mangled final word; either way the bug is silent until it is not.
// Every one of these is longer than the cap, so every one gets truncated.

func TestTruncateForSpeech_NeverSplitsARune(t *testing.T) {
	cases := map[string]string{
		"ascii":      strings.Repeat("a", maxTextLength+50),
		"accented":   strings.Repeat("é", maxTextLength),      // 2 bytes each
		"cjk":        strings.Repeat("語", maxTextLength),      // 3 bytes each
		"emoji":      strings.Repeat("🙂", maxTextLength),      // 4 bytes each
		"mixed":      strings.Repeat("aé語🙂", maxTextLength/2), // 1+2+3+4
		"zwj family": strings.Repeat("👩‍👩‍👧", 200),
	}
	for name, in := range cases {
		t.Run(name, func(t *testing.T) {
			got := truncateForSpeech(in)
			if !utf8.ValidString(got) {
				t.Fatalf("truncation produced invalid UTF-8 (%d bytes)", len(got))
			}
			if len(got) > maxTextLength {
				t.Fatalf("result is %d bytes, over the %d cap", len(got), maxTextLength)
			}
			if !strings.HasPrefix(in, got) {
				t.Fatal("result is not a prefix of the input")
			}
		})
	}
}

func TestTruncateForSpeech_LeavesShortTextAlone(t *testing.T) {
	for _, in := range []string{"", "hello", "héllo 🙂", strings.Repeat("a", maxTextLength)} {
		if got := truncateForSpeech(in); got != in {
			t.Fatalf("text within the cap was altered: %q -> %q", in, got)
		}
	}
}

// The boundary itself: a rune that straddles the cap must be dropped whole,
// not halved.
func TestTruncateForSpeech_AtTheExactBoundary(t *testing.T) {
	// 499 ASCII bytes then a 2-byte rune: the rune straddles byte 500.
	in := strings.Repeat("a", maxTextLength-1) + "é" + "tail"
	got := truncateForSpeech(in)

	if !utf8.ValidString(got) {
		t.Fatal("a rune straddling the cap was split")
	}
	if len(got) != maxTextLength-1 {
		t.Fatalf("got %d bytes, want %d (the straddling rune dropped whole)",
			len(got), maxTextLength-1)
	}
}

// One byte over: the last whole rune still survives.
func TestTruncateForSpeech_OneByteOver(t *testing.T) {
	in := strings.Repeat("a", maxTextLength+1)
	got := truncateForSpeech(in)
	if len(got) != maxTextLength {
		t.Fatalf("got %d bytes, want exactly the cap", len(got))
	}
	if !utf8.ValidString(got) {
		t.Fatal("invalid UTF-8")
	}
}

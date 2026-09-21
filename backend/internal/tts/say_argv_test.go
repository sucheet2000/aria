package tts

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

// The local fallback hands the caller's text to `say` as the final argv
// element. `say` parses its arguments as options wherever they appear, and it
// understands --output-file= and --input-file=, so a text field beginning with
// a dash stops being speech and becomes a file operation performed as the
// server user: an arbitrary overwrite, or the contents of any readable file
// spoken back down the HTTP response.
//
// This was inert while the command still carried --data-format=aiff, which
// `say` rejected before it did anything. Making the fallback work (42734a8)
// made this reachable, so the argv has to be closed properly.
func TestLocalFallback_TextIsNeverParsedAsAnOption(t *testing.T) {
	if !localFallbackAvailable() {
		t.Skipf("no local synthesizer here")
	}

	victim := filepath.Join(t.TempDir(), "victim.txt")
	const canary = "SECRET_CANARY_VALUE_12345"
	if err := os.WriteFile(victim, []byte(canary), 0o600); err != nil {
		t.Fatalf("seed victim: %v", err)
	}

	c := New("", "")
	c.SetPythonURL(newFailingUpstream(t).URL)

	stream, err := c.Open(context.Background(), "--output-file="+victim, "")
	if err == nil {
		stream.Close()
	}

	after, readErr := os.ReadFile(victim)
	if readErr != nil {
		t.Fatalf("the victim file was removed entirely: %v", readErr)
	}
	if string(after) != canary {
		t.Fatalf("the text field overwrote a file on disk: %d bytes, starts %q",
			len(after), string(after[:min(12, len(after))]))
	}
}

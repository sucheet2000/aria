package tts

import (
	"context"
	"os"
	"path/filepath"
	"strings"
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

// The invariant, asserted without a synthesizer so it runs in CI too. This is
// the guard that covers BOTH halves: a partial fix that stripped only
// "--output-file" from the text would leave --input-file — the half that reads
// backend/.env — wide open, and the behavioural test above would still pass.
func TestSayArgs_EndsOptionParsingBeforeTheText(t *testing.T) {
	const text = "--input-file=/etc/passwd"
	args := sayArgs("/tmp/out.aiff", text)

	if len(args) < 2 {
		t.Fatalf("argv too short: %q", args)
	}
	if got := args[len(args)-1]; got != text {
		t.Fatalf("text is not the final argument: %q", args)
	}
	if got := args[len(args)-2]; got != "--" {
		t.Fatalf("option parsing is not terminated before the text: %q", args)
	}
	// And nothing may quietly rewrite the caller's words on the way through.
	for _, a := range args[:len(args)-1] {
		if strings.Contains(a, text) {
			t.Fatalf("the text leaked into an earlier argument: %q", args)
		}
	}
}

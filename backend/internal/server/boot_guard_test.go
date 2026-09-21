package server

import (
	"context"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// F2 — the guard's CALL SITE, driven through the real Start.
//
// Two earlier attempts moved the seam without closing it: first the predicate
// was tested as a pure function, then the refusal was extracted to an error and
// the test called that error method directly. Both left `Start` free to stop
// calling it — `if err := error(nil); err != nil` passed the whole suite, and a
// binary built from that source served /metrics on a LAN address with no
// credential.
//
// The only thing that proves Start consults the guard is running Start. It
// ends in log.Fatal, so this re-executes the test binary as a subprocess and
// asserts the exit status — the standard Go idiom for an os.Exit path.
const bootGuardSubprocessEnv = "ARIA_TEST_BOOT_GUARD_SUBPROCESS"

func TestMetrics_StartConsultsTheBootGuard(t *testing.T) {
	if os.Getenv(bootGuardSubprocessEnv) == "1" {
		// Child: a public bind with no scrape credential. Start must refuse.
		s := newMetricsServer("http://127.0.0.1:1", os.Getenv("ARIA_TEST_BOOT_GUARD_TOKEN"))
		s.cfg.Host = "0.0.0.0"
		_ = s.Start(t.Context())
		return
	}

	run := func(t *testing.T, token string) (string, bool) {
		t.Helper()
		// Bounded: a Start that does NOT refuse goes on to bind and serve, so
		// the child would never exit. Not-exiting IS the failure, so it must be
		// a timeout rather than a hang.
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=TestMetrics_StartConsultsTheBootGuard")
		cmd.Env = append(os.Environ(),
			bootGuardSubprocessEnv+"=1",
			"ARIA_TEST_BOOT_GUARD_TOKEN="+token,
			// Past the Clerk guard, which fires first on a public bind. This
			// is also the compose default, so it doubles as proof that the
			// Clerk opt-out does not disarm the metrics guard.
			"ALLOW_INSECURE_NO_AUTH=1",
			allowInsecureMetricsEnv+"=",
		)
		out, err := cmd.CombinedOutput()
		if ctx.Err() != nil {
			// Still running when the deadline passed: it booted.
			return string(out) + "\n[child was still serving at the deadline]", true
		}
		return string(out), err == nil
	}

	out, ok := run(t, "")
	if ok {
		t.Fatalf("Start booted with /metrics open on a public bind; output:\n%s", out)
	}
	if !strings.Contains(out, "METRICS_TOKEN") {
		t.Fatalf("refused, but not for the metrics reason; output:\n%s", out)
	}
}

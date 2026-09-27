package server

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/sucheet2000/aria/backend/internal/config"
	"github.com/sucheet2000/aria/backend/internal/memory"
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

// unroutableBindHost is a non-loopback address that no machine owns (RFC 5737
// TEST-NET-1). isLoopback rejects it, so a boot guard must fire for it. If a
// guard is ever bypassed, Start's listener fails to bind rather than opening a
// LAN-reachable port with no credential, so running these tests against a
// broken guard never exposes anything.
const unroutableBindHost = "192.0.2.1"

// newBootGuardChild builds a boot-guard child with its bind host set BEFORE
// New, because New copies cfg.Addr() into the listener. Setting cfg.Host
// afterwards changes only what the guards see: the listener keeps the ":0" it
// was built with, which binds every interface, so a broken guard would expose
// an unauthenticated port instead of failing to bind.
func newBootGuardChild(host, metricsToken string) *Server {
	cfg := &config.Config{Host: host, Port: 0, MetricsToken: metricsToken}
	s := New(cfg, NewHub(), memory.New(5))
	s.pythonURL = "http://127.0.0.1:1"
	s.httpClient = &http.Client{Timeout: 5 * time.Second}
	return s
}

// The children above only stay safe if the listener binds the host the guards
// judge. This pins that for the address every boot-guard child uses.
func TestBootGuardChild_ListenerBindsTheHostTheGuardsSee(t *testing.T) {
	s := newBootGuardChild(unroutableBindHost, "")
	if got, want := s.httpServer.Addr, unroutableBindHost+":0"; got != want {
		t.Fatalf("listener Addr = %q, want %q: a guard bypass would bind somewhere the guard never judged", got, want)
	}
}

func TestMetrics_StartConsultsTheBootGuard(t *testing.T) {
	if os.Getenv(bootGuardSubprocessEnv) == "1" {
		// Child: a public bind with no scrape credential. Start must refuse.
		s := newBootGuardChild(unroutableBindHost, os.Getenv("ARIA_TEST_BOOT_GUARD_TOKEN"))
		_ = s.Start(t.Context())
		return
	}

	run := func(t *testing.T, token string) (string, bool) {
		t.Helper()
		// Bounded: a Start that does NOT refuse goes on to bind, and either
		// serves until the deadline or returns once the bind fails. Both are
		// the failure, so not-refusing must end in a timeout, not a hang.
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestMetrics_StartConsultsTheBootGuard$")
		cmd.Env = append(os.Environ(),
			bootGuardSubprocessEnv+"=1",
			"ARIA_TEST_BOOT_GUARD_TOKEN="+token,
			// Past the Clerk guard, which fires first on a public bind. This
			// is also the compose default, so it doubles as proof that the
			// Clerk opt-out does not disarm the metrics guard.
			allowInsecureNoAuthEnv+"=1",
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
		t.Fatalf("Start did not refuse to boot with /metrics open on a public bind; output:\n%s", out)
	}
	if !strings.Contains(out, "METRICS_TOKEN") {
		t.Fatalf("refused, but not for the metrics reason; output:\n%s", out)
	}
}

// SECURITY-MIDDLE-1 — the Clerk guard's call site, the same way.
//
// Start refuses to serve with auth off on a non-loopback bind. The only
// Start-level test above sets ALLOW_INSECURE_NO_AUTH=1 to get PAST this guard,
// so deleting or inverting the call left the whole suite green while a build of
// it would serve /api, /ws and /ws/audio on a public address to anyone.
const clerkBootGuardSubprocessEnv = "ARIA_TEST_CLERK_BOOT_GUARD_SUBPROCESS"

func TestClerk_StartConsultsTheBootGuard(t *testing.T) {
	if os.Getenv(clerkBootGuardSubprocessEnv) == "1" {
		// Child: no Clerk key, no opt-out, a public bind. A real scrape token
		// keeps the metrics guard quiet, so only the Clerk guard can refuse.
		s := newBootGuardChild(unroutableBindHost, testMetricsToken)
		_ = s.Start(t.Context())
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestClerk_StartConsultsTheBootGuard$")
	cmd.Env = append(os.Environ(),
		clerkBootGuardSubprocessEnv+"=1",
		allowInsecureNoAuthEnv+"=",
		allowInsecureMetricsEnv+"=",
	)
	out, err := cmd.CombinedOutput()
	if ctx.Err() != nil {
		t.Fatalf("Start booted with auth disabled on a public bind (still serving at the deadline); output:\n%s", out)
	}
	var exit *exec.ExitError
	if !errors.As(err, &exit) {
		t.Fatalf("Start did not refuse to boot with auth disabled on a public bind (err=%v); output:\n%s", err, out)
	}
	if !strings.Contains(string(out), "auth disabled on non-loopback bind") {
		t.Fatalf("refused, but not for the Clerk reason; output:\n%s", out)
	}
}

func TestClerk_BootGuardDecision(t *testing.T) {
	cases := []struct {
		name          string
		clerkKey      string
		host          string
		allowInsecure string
		wantRefuse    bool
	}{
		{"public bind, no key", "", "0.0.0.0", "", true},
		{"empty host is public, no key", "", "", "", true},
		{"public bind, key set", "sk_test_x", "0.0.0.0", "", false},
		{"loopback, no key", "", "127.0.0.1", "", false},
		{"public bind, deliberate opt-out", "", "0.0.0.0", "1", false},
		{"public bind, opt-out must be exactly 1", "", "0.0.0.0", "true", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := clerkGuardRefusesBoot(tc.clerkKey, tc.host, tc.allowInsecure); got != tc.wantRefuse {
				t.Fatalf("refuseBoot = %v, want %v", got, tc.wantRefuse)
			}
		})
	}
}

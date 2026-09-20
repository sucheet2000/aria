package cognition

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/rs/zerolog"
	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/memory"
)

// blockUntilCallerGone makes a fake upstream hold a request open until its
// caller goes away. The body must be drained first: net/http only starts the
// background read that notices a disconnected peer once the request body is
// consumed, so an upstream that ignores the body never sees the cancellation.
// The cap keeps a failing assertion from wedging httptest.Server.Close.
func blockUntilCallerGone(r *http.Request) {
	io.Copy(io.Discard, r.Body) //nolint:errcheck
	select {
	case <-r.Context().Done():
	case <-time.After(5 * time.Second):
	}
}

// R6: the cross-layer budget is browser 25s > Go upstream 20s > Python total
// 15s >= provider attempt 10s. Go's slice of it is pinned here so a later edit
// that silently widens or narrows it fails a test instead of a production turn.
func TestUpstreamTimeoutConstant(t *testing.T) {
	if UpstreamTimeout != 20*time.Second {
		t.Fatalf("UpstreamTimeout = %v, want 20s (must stay under the browser's 25s and above Python's 15s)", UpstreamTimeout)
	}
	if got := New("http://127.0.0.1:1", memory.New(5)).UpstreamTimeout(); got != UpstreamTimeout {
		t.Fatalf("client budget = %v, want the package default %v", got, UpstreamTimeout)
	}
}

// Python's total budget (15s) is shorter than Go's (20s), so Python giving up
// is the expected timeout path: its 504 must stay a 504 and not be charged to
// the server error rate as a 500.
func TestServeHTTP_UpstreamGatewayTimeoutStaysA504(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusGatewayTimeout)
		w.Write([]byte(`{"detail":"cognition timed out"}`))
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	h := NewHandler(c, zerolog.Nop())

	rec := httptest.NewRecorder()
	body := `{"message":"hi","session_id":"s"}`
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodPost, "/api/cognition", strings.NewReader(body)))

	if rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("status = %d, want 504 (an upstream timeout is not a server error)", rec.Code)
	}
	if got := rec.Body.String(); !strings.Contains(got, "cognition upstream timed out") {
		t.Errorf("body = %q, want the fixed edge timeout message", got)
	}
	if strings.Contains(rec.Body.String(), "detail") {
		t.Error("upstream body leaked through the edge")
	}
	if len(wm.All("")) != 0 {
		t.Error("a timed-out turn pushed to the working ring")
	}
}

// A sub-millisecond remainder must round UP to 1ms: flooring it to 0 would drop
// the header and let Python take its full budget while Go is already expiring.
func TestComplete_SubMillisecondBudgetStillSendsHeader(t *testing.T) {
	var header string
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		header = r.Header.Get(DeadlineHeader)
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"hi"}`))
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	ctx, cancel := context.WithTimeout(context.Background(), 400*time.Microsecond)
	defer cancel()
	_, _ = c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})

	if header != "" && header != "1" {
		t.Fatalf("%s = %q, want \"1\" (rounded up) or an expired-budget refusal", DeadlineHeader, header)
	}
}

// T4: cancelling the incoming request must cancel the in-flight upstream
// request promptly, Complete must return, and nothing may be left running.
func TestComplete_CancelPropagatesToUpstreamRequest(t *testing.T) {
	var handlerWG sync.WaitGroup
	upstreamCancelled := make(chan struct{})
	arrived := make(chan struct{})
	var once, arrivedOnce sync.Once

	handlerWG.Add(1)
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer handlerWG.Done()
		arrivedOnce.Do(func() { close(arrived) })
		blockUntilCallerGone(r)
		if r.Context().Err() != nil {
			once.Do(func() { close(upstreamCancelled) })
		}
	}))
	defer fake.Close()

	before := runtime.NumGoroutine()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	c.SetUpstreamTimeout(5 * time.Second)

	ctx, cancel := context.WithCancel(auth.WithOwner(context.Background(), "owner_a"))
	done := make(chan error, 1)
	go func() {
		_, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
		done <- err
	}()

	// Cancel only once the upstream handler is actually running: sleeping and
	// hoping leaves handlerWG.Wait() blocked forever when the race goes the
	// other way.
	select {
	case <-arrived:
	case <-time.After(5 * time.Second):
		t.Fatal("upstream never received the request")
	}
	cancel()

	select {
	case <-upstreamCancelled:
	case <-time.After(2 * time.Second):
		t.Fatal("upstream request context was not cancelled after the caller cancelled")
	}

	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("Complete err = %v, want context.Canceled", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("Complete did not return after the caller cancelled")
	}

	handlerWG.Wait()

	var after int
	for i := 0; i < 40; i++ {
		after = runtime.NumGoroutine()
		if after <= before+2 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("goroutines leaked: before=%d after=%d", before, after)
}

// T5 (client half): an upstream that blocks past the budget must surface a
// deadline error, not a generic transport error.
func TestComplete_UpstreamTimeoutIsDeadlineExceeded(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blockUntilCallerGone(r)
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	c.SetUpstreamTimeout(50 * time.Millisecond)

	ctx, cancel := context.WithTimeout(auth.WithOwner(context.Background(), "owner_a"), c.UpstreamTimeout())
	defer cancel()

	_, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Complete err = %v, want context.DeadlineExceeded", err)
	}
}

// T5 (handler half): the same timeout through ServeHTTP is a 504 with a fixed
// body. The upstream's own bytes must never reach the caller.
func TestServeHTTP_UpstreamTimeoutReturns504(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blockUntilCallerGone(r)
		w.Write([]byte("UPSTREAM_SECRET")) //nolint:errcheck
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	c.SetUpstreamTimeout(50 * time.Millisecond)
	h := NewHandler(c, zerolog.Nop())

	req := httptest.NewRequest(http.MethodPost, "/api/cognition",
		strings.NewReader(`{"message":"m","session_id":"s1"}`))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusGatewayTimeout {
		t.Fatalf("status = %d, want 504", rec.Code)
	}
	body := rec.Body.String()
	if !strings.Contains(body, "cognition upstream timed out") {
		t.Errorf("body = %q, want the fixed timeout message", body)
	}
	if strings.Contains(body, "UPSTREAM_SECRET") || strings.Contains(body, fake.URL) {
		t.Errorf("body leaked upstream detail: %q", body)
	}
}

// T13: a turn that times out or is cancelled must leave the owner's working
// ring untouched — a half-finished turn is not working state.
func TestComplete_NoRingMutationOnTimeout(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		blockUntilCallerGone(r)
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)
	c.SetUpstreamTimeout(50 * time.Millisecond)

	ctx, cancel := context.WithTimeout(auth.WithOwner(context.Background(), "owner_a"), c.UpstreamTimeout())
	defer cancel()

	if _, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"}); err == nil {
		t.Fatal("expected a timeout error")
	}
	if got := wm.All("owner_a"); len(got) != 0 {
		t.Fatalf("timed-out turn mutated the working ring: %v", got)
	}
}

// The remaining budget travels to Python as a whole-millisecond header so the
// downstream layer can size its own attempt. T14 rides along: a valid turn
// under a deadline still pushes the inference and derives the emotion.
func TestComplete_SendsRemainingDeadlineHeader(t *testing.T) {
	var got atomic.Value
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got.Store(r.Header.Get(DeadlineHeader))
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"user is happy about the build","natural_language_response":"ok"}`)) //nolint:errcheck
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)

	budget := 2 * time.Second
	ctx, cancel := context.WithTimeout(auth.WithOwner(context.Background(), "owner_a"), budget)
	defer cancel()

	resp, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if err != nil {
		t.Fatal(err)
	}

	raw, _ := got.Load().(string)
	if raw == "" {
		t.Fatalf("%s header missing", DeadlineHeader)
	}
	ms, err := strconv.Atoi(raw)
	if err != nil {
		t.Fatalf("%s = %q, want whole milliseconds: %v", DeadlineHeader, raw, err)
	}
	if ms <= 0 || int64(ms) > budget.Milliseconds() {
		t.Fatalf("%s = %d, want 0 < ms <= %d", DeadlineHeader, ms, budget.Milliseconds())
	}

	// T14: the happy path is unchanged under a deadline.
	if ring := wm.All("owner_a"); len(ring) != 1 || ring[0] != "user is happy about the build" {
		t.Fatalf("ring = %v, want the valid inference", ring)
	}
	if resp.AvatarEmotion != "happy" {
		t.Errorf("avatar_emotion = %q, want happy", resp.AvatarEmotion)
	}
}

func TestComplete_OmitsDeadlineHeaderWithoutDeadline(t *testing.T) {
	seen := make(chan bool, 1)
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, ok := r.Header[http.CanonicalHeaderKey(DeadlineHeader)]
		seen <- ok
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"symbolic_inference":"","natural_language_response":"ok"}`)) //nolint:errcheck
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	if _, err := c.Complete(auth.WithOwner(context.Background(), "owner_a"), CognitionRequest{Message: "m", SessionID: "s1"}); err != nil {
		t.Fatal(err)
	}
	if <-seen {
		t.Fatalf("%s must be absent when the caller set no deadline", DeadlineHeader)
	}
}

// An already-expired budget must fail before the HTTP call: spending an
// upstream turn we can no longer wait for costs money for nothing.
func TestComplete_ExpiredBudgetSkipsUpstream(t *testing.T) {
	var calls atomic.Int32
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		w.Write([]byte(`{}`)) //nolint:errcheck
	}))
	defer fake.Close()

	wm := memory.New(5)
	c := New(fake.URL, wm)

	ctx, cancel := context.WithDeadline(auth.WithOwner(context.Background(), "owner_a"), time.Now().Add(-time.Millisecond))
	defer cancel()

	_, err := c.Complete(ctx, CognitionRequest{Message: "m", SessionID: "s1"})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Complete err = %v, want context.DeadlineExceeded", err)
	}
	var urlErr *url.Error
	if errors.As(err, &urlErr) {
		t.Fatalf("expired budget still went through the HTTP client: %v", err)
	}
	if n := calls.Load(); n != 0 {
		t.Fatalf("upstream called %d times on an expired budget, want 0", n)
	}
}

// A caller that hung up gets no body: writing to a gone client is pointless,
// and a 500 would pollute the error rate with a client-side disconnect.
func TestServeHTTP_ClientDisconnectWritesNoBody(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{}`)) //nolint:errcheck
	}))
	defer fake.Close()

	c := New(fake.URL, memory.New(5))
	h := NewHandler(c, zerolog.Nop())

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	req := httptest.NewRequest(http.MethodPost, "/api/cognition",
		strings.NewReader(`{"message":"m","session_id":"s1"}`)).WithContext(ctx)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Body.Len() != 0 {
		t.Errorf("wrote %d bytes to a disconnected caller: %q", rec.Body.Len(), rec.Body.String())
	}
	if rec.Code == http.StatusInternalServerError {
		t.Error("a client disconnect must not be recorded as a 500")
	}
}

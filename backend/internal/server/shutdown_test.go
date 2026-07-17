package server

import (
	"context"
	"sync"
	"testing"
	"time"
)

// recorder captures the order of shutdown events under a mutex.
type recorder struct {
	mu     sync.Mutex
	events []string
}

func (r *recorder) add(e string) {
	r.mu.Lock()
	r.events = append(r.events, e)
	r.mu.Unlock()
}

func (r *recorder) snapshot() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]string, len(r.events))
	copy(out, r.events)
	return out
}

func (r *recorder) indexOf(e string) int {
	for i, ev := range r.snapshot() {
		if ev == e {
			return i
		}
	}
	return -1
}

type fakeWorker struct {
	rec   *recorder
	name  string
	delay time.Duration
}

func (f *fakeWorker) Stop() {
	if f.delay > 0 {
		time.Sleep(f.delay)
	}
	f.rec.add(f.name)
}

type fakeHTTP struct {
	rec *recorder
}

func (f *fakeHTTP) Shutdown(ctx context.Context) error {
	f.rec.add("http-shutdown")
	return nil
}

func TestGracefulShutdown_StopsWorkersBeforeCancel(t *testing.T) {
	rec := &recorder{}
	worker := &fakeWorker{rec: rec, name: "worker-stop"}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer ctxCancel()

	GracefulShutdown(ctx, func() { rec.add("cancel") }, httpSrv, worker)

	events := rec.snapshot()
	if len(events) == 0 || events[len(events)-1] != "cancel" {
		t.Fatalf("expected cancel to be the final event, got %v", events)
	}
	if rec.indexOf("worker-stop") == -1 {
		t.Fatalf("worker Stop was never called, events: %v", events)
	}
	if rec.indexOf("worker-stop") > rec.indexOf("cancel") {
		t.Fatalf("worker Stop must run before cancel, got %v", events)
	}
	if rec.indexOf("http-shutdown") == -1 {
		t.Fatalf("http Shutdown was never called, events: %v", events)
	}
}

func TestGracefulShutdown_BoundedBySlowWorker(t *testing.T) {
	rec := &recorder{}
	slow := &fakeWorker{rec: rec, name: "slow", delay: 2 * time.Second}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer ctxCancel()

	cancelled := make(chan struct{})

	start := time.Now()
	GracefulShutdown(ctx, func() { close(cancelled) }, httpSrv, slow)
	elapsed := time.Since(start)

	if elapsed > time.Second {
		t.Fatalf("shutdown did not respect the deadline: took %v", elapsed)
	}
	select {
	case <-cancelled:
	default:
		t.Fatal("root context was not cancelled on deadline")
	}
}

func TestGracefulShutdown_FastPathNoFixedSleep(t *testing.T) {
	rec := &recorder{}
	worker := &fakeWorker{rec: rec, name: "worker-stop"}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), ShutdownTimeout)
	defer ctxCancel()

	start := time.Now()
	GracefulShutdown(ctx, func() {}, httpSrv, worker)
	elapsed := time.Since(start)

	if elapsed > 500*time.Millisecond {
		t.Fatalf("fast shutdown should return promptly, not sleep: took %v", elapsed)
	}
}

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

type fakeGRPC struct {
	rec      *recorder
	block    chan struct{} // when non-nil, GracefulStop blocks until closed
	stopOnce sync.Once
}

func (f *fakeGRPC) GracefulStop() {
	if f.block != nil {
		<-f.block
	}
	f.rec.add("grpc-graceful")
}

func (f *fakeGRPC) Stop() {
	f.rec.add("grpc-hard-stop")
	if f.block != nil {
		f.stopOnce.Do(func() { close(f.block) })
	}
}

func TestGracefulShutdown_StopsWorkersBeforeCancel(t *testing.T) {
	rec := &recorder{}
	worker := &fakeWorker{rec: rec, name: "worker-stop"}
	grpc := &fakeGRPC{rec: rec}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer ctxCancel()

	GracefulShutdown(ctx, func() { rec.add("cancel") }, httpSrv, grpc, worker)

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
	if rec.indexOf("grpc-graceful") == -1 {
		t.Fatalf("grpc GracefulStop was never called, events: %v", events)
	}
}

func TestGracefulShutdown_BoundedBySlowWorker(t *testing.T) {
	rec := &recorder{}
	slow := &fakeWorker{rec: rec, name: "slow", delay: 2 * time.Second}
	grpc := &fakeGRPC{rec: rec}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer ctxCancel()

	cancelled := make(chan struct{})

	start := time.Now()
	GracefulShutdown(ctx, func() { close(cancelled) }, httpSrv, grpc, slow)
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
	grpc := &fakeGRPC{rec: rec}
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), ShutdownTimeout)
	defer ctxCancel()

	start := time.Now()
	GracefulShutdown(ctx, func() {}, httpSrv, grpc, worker)
	elapsed := time.Since(start)

	if elapsed > 500*time.Millisecond {
		t.Fatalf("fast shutdown should return promptly, not sleep: took %v", elapsed)
	}
}

func TestGracefulShutdown_GRPCFallbackToHardStop(t *testing.T) {
	rec := &recorder{}
	grpc := &fakeGRPC{rec: rec, block: make(chan struct{})} // GracefulStop hangs
	httpSrv := &fakeHTTP{rec: rec}

	ctx, ctxCancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer ctxCancel()

	start := time.Now()
	GracefulShutdown(ctx, func() {}, httpSrv, grpc)
	elapsed := time.Since(start)

	if elapsed > time.Second {
		t.Fatalf("expected bounded shutdown when GracefulStop hangs, took %v", elapsed)
	}

	// The hard Stop() fallback fires at the deadline in a shutdown goroutine;
	// give it a bounded window to be recorded.
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && rec.indexOf("grpc-hard-stop") == -1 {
		time.Sleep(5 * time.Millisecond)
	}
	if rec.indexOf("grpc-hard-stop") == -1 {
		t.Fatalf("expected hard Stop() fallback when GracefulStop exceeds budget, events: %v", rec.snapshot())
	}
}

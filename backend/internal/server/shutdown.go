package server

import (
	"context"
	"sync"
	"time"

	"github.com/rs/zerolog/log"
)

// ShutdownTimeout bounds the entire graceful-shutdown sequence. It is kept below
// Railway's default 10s SIGTERM grace window so every step (HTTP drain, worker
// stop) completes before the platform force-kills the process.
const ShutdownTimeout = 8 * time.Second

// httpShutdowner gracefully stops an HTTP server, refusing new connections and
// draining in-flight requests. Satisfied by *Server.
type httpShutdowner interface {
	Shutdown(context.Context) error
}

// workerStopper is implemented by the subprocess workers (audio, vision).
type workerStopper interface {
	Stop()
}

// GracefulShutdown performs an ordered, bounded shutdown within ctx's deadline:
//  1. stop accepting new connections and drain in-flight HTTP/WS work,
//  2. stop the subprocess workers via their own SIGTERM/flush path,
//  3. cancel the root context last, so a still-running subprocess is only
//     force-killed after the graceful path has had the full budget.
//
// Steps 1-2 run concurrently under the shared deadline; cancel runs only after
// they complete or the deadline elapses — never after a fixed sleep.
func GracefulShutdown(ctx context.Context, cancel context.CancelFunc, httpSrv httpShutdowner, workers ...workerStopper) {
	var wg sync.WaitGroup

	if httpSrv != nil {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if err := httpSrv.Shutdown(ctx); err != nil {
				log.Warn().Err(err).Msg("http server shutdown error")
			}
		}()
	}

	for _, wk := range workers {
		if wk == nil {
			continue
		}
		wg.Add(1)
		go func(s workerStopper) {
			defer wg.Done()
			s.Stop()
		}(wk)
	}

	done := make(chan struct{})
	go func() {
		wg.Wait()
		close(done)
	}()

	select {
	case <-done:
		log.Info().Msg("graceful shutdown complete")
	case <-ctx.Done():
		log.Warn().Msg("shutdown deadline exceeded, forcing stop")
	}

	// Cancel last: releases the workers' restart loops and force-kills any
	// subprocess that ignored SIGTERM — never before the graceful path runs.
	cancel()
}

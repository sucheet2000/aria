package server

import (
	"encoding/json"
	"io"
	"net/http"

	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// readyCheck is a named liveness probe for a subprocess worker.
type readyCheck struct {
	name string
	ok   func() bool
}

// AddReadyCheck registers a worker liveness probe consulted by GET /ready.
// It must be called before the server begins serving.
func (s *Server) AddReadyCheck(name string, ok func() bool) {
	s.readyChecks = append(s.readyChecks, readyCheck{name: name, ok: ok})
}

// handleReady reports whether the edge can serve: Python must be reachable via
// its internal /ready endpoint and every registered worker probe must pass. It
// returns 200 when all checks are healthy and 503 otherwise. The cheap /health
// endpoint remains liveness-only.
func (s *Server) handleReady(w http.ResponseWriter, r *http.Request) {
	checks := make(map[string]string)
	ready := true

	pythonOK := s.pythonReady(r)
	checks["python"] = upDown(pythonOK)
	if !pythonOK {
		ready = false
	}

	for _, c := range s.readyChecks {
		ok := c.ok()
		checks[c.name] = upDown(ok)
		if !ok {
			ready = false
		}
	}

	status := "ready"
	code := http.StatusOK
	if !ready {
		status = "not ready"
		code = http.StatusServiceUnavailable
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(map[string]any{ //nolint:errcheck
		"status": status,
		"checks": checks,
	})
}

// pythonReady pings the Python internal /ready endpoint, forwarding the internal
// auth secret and request id. It returns true only on a 200 response.
func (s *Server) pythonReady(r *http.Request) bool {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, s.pythonURL+"/ready", nil)
	if err != nil {
		return false
	}
	auth.SetInternalAuth(req, s.cfg.InternalAuthSecret)
	reqid.SetHeader(req, r.Context())

	resp, err := s.httpClient.Do(req)
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body) //nolint:errcheck
	return resp.StatusCode == http.StatusOK
}

func upDown(ok bool) string {
	if ok {
		return "up"
	}
	return "down"
}

package server

import (
	"io"
	"net/http"

	"github.com/sucheet2000/aria/backend/internal/auth"
	"github.com/sucheet2000/aria/backend/internal/reqid"
)

// handleMetricsProxy exposes a public GET /metrics that streams the Python
// service's internal /metrics through the edge, forwarding the internal auth
// secret and request id. Python is never exposed to the network directly.
func (s *Server) handleMetricsProxy(w http.ResponseWriter, r *http.Request) {
	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, s.pythonURL+"/metrics", nil)
	if err != nil {
		http.Error(w, `{"error":"internal error"}`, http.StatusInternalServerError)
		return
	}
	auth.SetInternalAuth(req, s.cfg.InternalAuthSecret)
	reqid.SetHeader(req, r.Context())

	resp, err := s.httpClient.Do(req)
	if err != nil {
		http.Error(w, `{"error":"python service unavailable"}`, http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if ct := resp.Header.Get("Content-Type"); ct != "" {
		w.Header().Set("Content-Type", ct)
	}
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body) //nolint:errcheck
}

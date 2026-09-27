package server

import (
	"net"
	"testing"

	"github.com/sucheet2000/aria/backend/internal/config"
)

func TestIsLoopback(t *testing.T) {
	tests := []struct {
		host string
		want bool
	}{
		{"127.0.0.1", true},
		{"localhost", true},
		{"::1", true},
		{"", false},
		{"0.0.0.0", false},
		{"::", false},
		{"192.168.1.10", false},
		{"aria.example.com", false},
	}

	for _, tt := range tests {
		t.Run(tt.host, func(t *testing.T) {
			if got := isLoopback(tt.host); got != tt.want {
				t.Errorf("isLoopback(%q) = %v, want %v", tt.host, got, tt.want)
			}
		})
	}
}

// isLoopback decides whether the server may boot without Clerk or a metrics
// token, so it has to agree with what the listener actually binds. The table
// above once certified "" as loopback, but Config.Addr renders an empty host as
// ":port", and net.Listen treats a missing host as every interface.
//
// This resolves each host exactly as net.Listen does (a nil or unspecified IP
// means all interfaces) without binding anything, so no test ever opens a
// wildcard listener.
func TestIsLoopback_AgreesWithWhatTheListenerBinds(t *testing.T) {
	if got := (&config.Config{Host: "", Port: 8080}).Addr(); got != ":8080" {
		t.Fatalf("Addr() for an empty host = %q, want the bare %q that net.Listen binds on every interface", got, ":8080")
	}

	for _, host := range []string{"", "0.0.0.0", "::", "127.0.0.1", "localhost", "::1"} {
		addr := net.JoinHostPort(host, "0")
		resolved, err := net.ResolveTCPAddr("tcp", addr)
		if err != nil {
			t.Fatalf("resolve %q: %v", addr, err)
		}
		onlyLoopback := resolved.IP != nil && resolved.IP.IsLoopback()
		if got := isLoopback(host); got != onlyLoopback {
			t.Errorf("isLoopback(%q) = %v, but %q binds %v (loopback only: %v)",
				host, got, addr, resolved.IP, onlyLoopback)
		}
	}
}

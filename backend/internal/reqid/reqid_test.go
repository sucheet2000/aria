package reqid

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestNew_UniqueNonEmpty(t *testing.T) {
	a, b := New(), New()
	if a == "" || b == "" {
		t.Fatal("New returned an empty id")
	}
	if a == b {
		t.Fatalf("New returned duplicate ids: %q", a)
	}
	if len(a) != 36 {
		t.Errorf("id %q length = %d, want 36", a, len(a))
	}
}

func TestFromContext_RoundTrip(t *testing.T) {
	ctx := WithID(context.Background(), "abc-123")
	if got := FromContext(ctx); got != "abc-123" {
		t.Errorf("FromContext = %q, want abc-123", got)
	}
}

func TestFromContext_Empty(t *testing.T) {
	if got := FromContext(context.Background()); got != "" {
		t.Errorf("FromContext = %q, want empty", got)
	}
}

func TestSetHeader_SetsWhenPresent(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	SetHeader(req, WithID(context.Background(), "rid-1"))
	if got := req.Header.Get(Header); got != "rid-1" {
		t.Errorf("%s = %q, want rid-1", Header, got)
	}
}

func TestSetHeader_NoHeaderWhenAbsent(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	SetHeader(req, context.Background())
	if _, ok := req.Header[Header]; ok {
		t.Errorf("%s should not be set when ctx carries no id", Header)
	}
}

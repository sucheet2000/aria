package tts

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHandler_OversizedBodyReturns413(t *testing.T) {
	h := NewHandler(New("", ""))

	big := strings.Repeat("a", (64<<10)+1)
	body := `{"text":"` + big + `"}`
	req := httptest.NewRequest(http.MethodPost, "/api/tts", strings.NewReader(body))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("status = %d, want 413", rec.Code)
	}
}

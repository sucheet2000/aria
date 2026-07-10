package auth

import (
	"context"
	"fmt"

	"github.com/clerk/clerk-sdk-go/v2"
	"github.com/clerk/clerk-sdk-go/v2/jwks"
	"github.com/clerk/clerk-sdk-go/v2/jwt"
)

// ClerkVerifier verifies Clerk session JWTs using the Clerk backend SDK.
type ClerkVerifier struct {
	issuer     string
	jwksClient *jwks.Client
}

// NewClerkVerifier builds a Verifier configured with the Clerk secret key and,
// optionally, the expected token issuer. An empty issuer disables the issuer
// check.
func NewClerkVerifier(secretKey, issuer string) *ClerkVerifier {
	config := &clerk.ClientConfig{}
	config.Key = clerk.String(secretKey)
	return &ClerkVerifier{
		issuer:     issuer,
		jwksClient: jwks.NewClient(config),
	}
}

// Verify validates the session token and returns the Clerk user id (sub claim).
func (c *ClerkVerifier) Verify(ctx context.Context, token string) (string, error) {
	claims, err := jwt.Verify(ctx, &jwt.VerifyParams{
		Token:      token,
		JWKSClient: c.jwksClient,
	})
	if err != nil {
		return "", fmt.Errorf("verify clerk session token: %w", err)
	}
	if c.issuer != "" && claims.Issuer != c.issuer {
		return "", fmt.Errorf("unexpected token issuer %q", claims.Issuer)
	}
	if claims.Subject == "" {
		return "", fmt.Errorf("clerk session token missing sub claim")
	}
	return claims.Subject, nil
}

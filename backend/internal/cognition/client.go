package cognition

import (
	"context"
	"fmt"
	"time"

	"github.com/anthropics/anthropic-sdk-go"
	"github.com/anthropics/anthropic-sdk-go/option"
	"github.com/rs/zerolog"
)

// Client wraps the Anthropic API client.
type Client struct {
	anthropic *anthropic.Client
	log       zerolog.Logger
}

// New creates a Client configured with the given API key.
func New(apiKey string, log zerolog.Logger) *Client {
	c := anthropic.NewClient(option.WithAPIKey(apiKey))
	return &Client{
		anthropic: &c,
		log:       log,
	}
}

// ConversationMessage represents a single turn in conversation history.
type ConversationMessage struct {
	Role    string
	Content string
}

// CognitionRequest holds everything needed to produce a cognition response.
type CognitionRequest struct {
	Message             string
	VisionState         VisionStateContext
	ConversationHistory []ConversationMessage
}

// CognitionResponse is the result returned to the caller.
type CognitionResponse struct {
	Response          string
	EmotionSuggestion string
	ProcessingMs      int64
}

// Complete sends the request to the Anthropic API and returns a structured response.
func (c *Client) Complete(ctx context.Context, req CognitionRequest) (CognitionResponse, error) {
	start := time.Now()

	systemPrompt := BuildSystemPrompt(req.VisionState)

	messages := make([]anthropic.MessageParam, 0, len(req.ConversationHistory)+1)
	for _, turn := range req.ConversationHistory {
		block := anthropic.NewTextBlock(turn.Content)
		switch turn.Role {
		case "assistant":
			messages = append(messages, anthropic.NewAssistantMessage(block))
		default:
			messages = append(messages, anthropic.NewUserMessage(block))
		}
	}
	messages = append(messages, anthropic.NewUserMessage(anthropic.NewTextBlock(req.Message)))

	resp, err := c.anthropic.Messages.New(ctx, anthropic.MessageNewParams{
		Model:     anthropic.ModelClaudeHaiku4_5,
		MaxTokens: 150,
		System: []anthropic.TextBlockParam{
			{Text: systemPrompt},
		},
		Messages: messages,
	})
	if err != nil {
		return CognitionResponse{}, fmt.Errorf("anthropic messages.new: %w", err)
	}

	if len(resp.Content) == 0 {
		return CognitionResponse{}, fmt.Errorf("anthropic returned empty content")
	}

	text := resp.Content[0].AsText().Text
	suggestion := SuggestEmotion(text)

	return CognitionResponse{
		Response:          text,
		EmotionSuggestion: suggestion,
		ProcessingMs:      time.Since(start).Milliseconds(),
	}, nil
}

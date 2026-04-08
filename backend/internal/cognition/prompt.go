package cognition

import (
	"fmt"
	"strings"
)

// BuildSystemPrompt constructs the system prompt for the language model based on
// the current perception frame.
func BuildSystemPrompt(frame PerceptionFrame) string {
	var sb strings.Builder

	sb.WriteString("You are ARIA, a perceptive AI companion with the ability to see and understand the person you are speaking with. ")
	sb.WriteString("You are connected to a camera and can observe the user in real time. ")

	if !frame.FaceDetected {
		sb.WriteString("The user does not appear to be in frame right now -- they may have stepped away. ")
		sb.WriteString("Acknowledge their absence briefly if relevant, and stay ready for when they return. ")
	} else {
		emotion := frame.Emotion
		if emotion == "" {
			emotion = "neutral"
		}
		sb.WriteString(fmt.Sprintf("You can see that the user currently appears %s. ", emotion))

		headNote := describeHeadPose(frame.Pitch, frame.Yaw)
		if headNote != "" {
			sb.WriteString(headNote + " ")
		}
	}

	sb.WriteString("Keep all responses to 2-3 sentences. ")
	sb.WriteString("Speak naturally and directly, as if you are talking to the person face to face. ")
	sb.WriteString("Never use lists, markdown, bullet points, headers, or any other formatting. ")
	sb.WriteString("Do not use filler phrases like 'Certainly!' or 'Of course!'. ")
	sb.WriteString("Respond as if speaking aloud, not writing.")

	return sb.String()
}

// describeHeadPose returns a natural-language description of head orientation
// when the pose is notable. Returns an empty string for near-neutral poses.
func describeHeadPose(pitch, yaw float64) string {
	const threshold = 10.0

	switch {
	case pitch < -threshold:
		return "Their head is tilted slightly downward."
	case pitch > threshold:
		return "Their head is tilted slightly upward."
	case yaw < -threshold:
		return "They appear to be looking to their right."
	case yaw > threshold:
		return "They appear to be looking to their left."
	default:
		return ""
	}
}

// SuggestEmotion returns a display emotion label derived from keyword scanning
// of the model response text.
func SuggestEmotion(response string) string {
	lower := strings.ToLower(response)

	switch {
	case containsAny(lower, "sorry", "unfortunate", "sad"):
		return "sad"
	case containsAny(lower, "great", "wonderful", "happy", "glad"):
		return "happy"
	case containsAny(lower, "interesting", "curious", "wonder"):
		return "thoughtful"
	case containsAny(lower, "exciting", "amazing", "incredible"):
		return "excited"
	case containsAny(lower, "surprised", "unexpected", "wow"):
		return "surprised"
	default:
		return "neutral"
	}
}

func containsAny(s string, keywords ...string) bool {
	for _, kw := range keywords {
		if strings.Contains(s, kw) {
			return true
		}
	}
	return false
}

// Module-level hook shared between useTTS (the producer) and useWebSocket (the
// caller). Kept in its own tiny module so the dependency stays one-way — useTTS
// already imports wsSendRef from useWebSocket, and importing back would close a
// cycle. Follows the exported-ref convention (wsSendRef, visionCaptureActiveRef,
// abortCognitionRef).
//
// V3: the tts_mute / tts_unmute control messages are fire-and-forget and are
// dropped silently whenever the main socket is not open. So every time that
// socket comes up, the browser re-states whether ARIA is currently speaking
// rather than trusting the single message it sent when speech began.
export const ttsResyncRef: { current: (() => void) | null } = { current: null };

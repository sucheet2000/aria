// Module-level flag shared between useVisionCapture (the producer) and
// useWebSocket (the consumer of the server's vision_state). Kept in its own tiny
// module so useWebSocket can read it without importing the MediaPipe-heavy
// useVisionCapture module. Follows the exported-ref convention (wsSendRef,
// abortCognitionRef).
//
// When the browser is producing PerceptionFrames locally, this is true and the
// server's vision_state is ignored — the local producer is the source.
export const visionCaptureActiveRef: { current: boolean } = { current: false };

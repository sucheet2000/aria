// The single authority for "ARIA is audibly speaking right now".
//
// V3 kept this count inside useTTS and used it only to decide when to send
// tts_mute / tts_unmute to the server. That made the duplex guarantee depend on
// a control message being delivered — and it is dropped silently whenever the
// main WebSocket is down, while the microphone rides a separate socket that
// keeps streaming. V3.1 moves the count here so the PCM uplink can read the
// same state directly and drop frames locally, with no server round trip and
// nothing to lose in flight.
//
// One count, not two. useTTS owns the lifecycle and is the only writer;
// useAudioCapture is a reader. Two independent counters could disagree, and a
// disagreement here means either ARIA hears itself or the microphone goes deaf.
//
// Kept in its own tiny module so the dependency graph stays one-way — the
// exported-ref convention already used by wsSendRef, visionCaptureActiveRef and
// ttsResyncRef.
let holds = 0;

/** True while at least one speech lifecycle is in flight. */
export function isTtsCaptureSuppressed(): boolean {
  return holds > 0;
}

/** Current hold count. Exported for the TTS lifecycle and for assertions. */
export function ttsSpeakingHolds(): number {
  return holds;
}

/** Take a hold. Called before any audible output begins. */
export function addTtsSpeakingHold(): void {
  holds += 1;
}

/** Drop a hold. Floors at zero so a stray release can never go negative. */
export function dropTtsSpeakingHold(): void {
  holds = Math.max(0, holds - 1);
}

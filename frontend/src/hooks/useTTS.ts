"use client";

import { useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useAriaStore } from "@/store/ariaStore";
import { wsSendRef } from "./useWebSocket";
import { ttsResyncRef } from "./ttsResyncState";
import {
  addTtsSpeakingHold,
  dropTtsSpeakingHold,
  ttsSpeakingHolds,
} from "./ttsSpeakingState";
import { API_BASE } from "@/lib/config";

export const ttsAudioRef: { current: HTMLAudioElement | null } = {
  current: null,
};

export const speakRef: {
  current: ((text: string, emotion?: string) => Promise<void>) | null;
} = {
  current: null,
};

// ── V3 / V3.1: ARIA must not hear itself ────────────────────────────────────
// Suppression happens in two places, and the browser one is the load-bearing
// half. Locally, useAudioCapture drops PCM frames while a hold is held, so no
// audio leaves the machine no matter what the network is doing. On the server,
// the Go edge drops this owner's frames when it receives tts_mute — defence in
// depth, and the only thing that can protect against a producer other than this
// page. The browser owes one thing: hold for exactly as long as ARIA is
// audibly speaking, on EVERY path, including the Web Speech fallback.
//
// A count, not a boolean. Two speech lifecycles can overlap: the remote clip's
// teardown runs while the fallback has already started talking. Whoever
// finishes first must not re-open the mic while the other is still speaking.
//
// The count lives in ttsSpeakingState so the capture hook reads exactly the
// state this lifecycle writes. One authority, so the two can never disagree.
// Every release below is driven by a browser event, and browsers do not always
// send one: a media element paused by a hardware key fires neither `ended` nor
// `error`, and a long utterance can be dropped silently. Since V3.1 the gate is
// local, so a stranded hold means this page's microphone is dead until reload,
// with no server timeout able to reach it. Each hold therefore carries its own
// deadline, generous enough that no real reply is ever cut short: a floor plus
// time proportional to the text, at a pace far slower than any voice speaks.
const HOLD_FLOOR_MS = 30_000;
const HOLD_MS_PER_CHAR = 150; // ~6.7 chars/s; real speech is roughly twice that

function holdDeadlineMs(text: string): number {
  return HOLD_FLOOR_MS + text.length * HOLD_MS_PER_CHAR;
}

function acquireMute(text: string): () => void {
  // Local suppression first, then the server attempt, then playback. The order
  // matters: the send can be dropped, the local gate cannot.
  const first = ttsSpeakingHolds() === 0;
  addTtsSpeakingHold();
  if (first) wsSendRef.current?.({ type: "tts_mute" });

  let released = false;
  const release = (): void => {
    // Idempotent. One utterance can fire both onend and onerror, and a
    // cancelled one may fire neither, so release is also called defensively.
    if (released) return;
    released = true;
    clearTimeout(watchdog);
    dropTtsSpeakingHold();
    if (ttsSpeakingHolds() === 0) wsSendRef.current?.({ type: "tts_unmute" });
  };

  // Releases only this hold, so an overlapping one keeps the gate shut.
  const watchdog = setTimeout(release, holdDeadlineMs(text));
  return release;
}

// The control messages are fire-and-forget: the socket drops them when it is
// not open, and neither side acknowledges. So the browser re-states its whole
// duplex intent every time the main socket comes up, rather than relying on the
// single edge-triggered message it sent when speech began. A mute lost to a
// reconnect is re-asserted within milliseconds, and a mute the server is still
// holding for a page that has since gone away is cleared by the fresh page,
// which owes nothing. Level-triggered, so it is correct in both directions.
export function resyncTtsMuteState(): void {
  wsSendRef.current?.({
    type: ttsSpeakingHolds() > 0 ? "tts_mute" : "tts_unmute",
  });
}

ttsResyncRef.current = resyncTtsMuteState;

// Test-only window into the hold count: proves no hold leaks across cycles.
export function __ttsMuteHoldCount(): number {
  return ttsSpeakingHolds();
}

let releaseBrowserSpeech: (() => void) | null = null;

// The Go TTS handler truncates to this before calling ElevenLabs, but the
// fallback was handed the raw reply, so a long answer became minutes of speech
// — past the point where engines silently stop without firing `end`, and long
// enough to keep the microphone shut for just as long. Cap it here too, so both
// voices speak the same amount and the hold deadline stays generous.
const MAX_SPOKEN_CHARS = 500;

function speakWithBrowser(fullText: string): void {
  if (!("speechSynthesis" in window)) return;
  const text = fullText.slice(0, MAX_SPOKEN_CHARS);

  // Acquire BEFORE cancelling the previous utterance, so the count never falls
  // to zero between two pieces of ARIA speech — no momentarily open mic.
  const release = acquireMute(text);
  const previous = releaseBrowserSpeech;
  releaseBrowserSpeech = release;

  const finish = (): void => {
    if (releaseBrowserSpeech === release) releaseBrowserSpeech = null;
    release();
  };

  try {
    window.speechSynthesis.cancel();
    // cancel() is specified to fire 'end' on the cancelled utterance; release
    // the old hold directly too, in case a browser does not.
    previous?.();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.92;
    utterance.pitch = 1.0;
    utterance.volume = 1.0;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(
      (v) => v.name.includes("Samantha") || v.name.includes("Karen")
    );
    if (preferred) utterance.voice = preferred;

    utterance.onend = finish;
    utterance.onerror = finish;

    window.speechSynthesis.speak(utterance);
  } catch {
    // Speech never started; do not strand the mute.
    finish();
  }
}

export function useTTS() {
  const { getToken } = useAuth();
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setIsSpeaking = useAriaStore((s) => s.setIsSpeaking);

  async function speak(text: string, emotion?: string): Promise<void> {
    if (!text || isPlaying) return;

    setIsPlaying(true);
    setError(null);

    // Held only by the remote-playback path. Null until playback is about to
    // start, so the error paths below never release a mute they never took.
    let releaseRemote: (() => void) | null = null;

    try {
      const token = await getToken();
      const response = await fetch(`${API_BASE}/api/tts`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(emotion ? { text, emotion } : { text }),
        signal: AbortSignal.timeout(15000),
      });

      if (!response.ok) {
        throw new Error(`TTS request failed: HTTP ${response.status}`);
      }

      const blob = new Blob([await response.arrayBuffer()], { type: "audio/mpeg" });
      if (blob.size < 100) {
        // Unusable body: the fallback speaks, and takes its own mute first.
        speakWithBrowser(text);
        setIsPlaying(false);
        return;
      }
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      ttsAudioRef.current = audio;
      setIsSpeaking(true);
      releaseRemote = acquireMute(text);   // mute BEFORE play()

      const endRemote = (): void => {
        URL.revokeObjectURL(url);
        setIsPlaying(false);
        setIsSpeaking(false);
        releaseRemote?.();
      };

      audio.onended = endRemote;
      audio.onerror = endRemote;
      // A hardware media key or an OS audio interruption stops playback
      // without firing either of the above. Treat it as the end of speech:
      // nothing in the app pauses this element, so a pause means the user or
      // the platform stopped ARIA, and the microphone must come back.
      audio.onpause = endRemote;

      try {
        await audio.play();
      } catch {
        // Playback never started. The fallback takes its own hold first, so the
        // count never reaches zero and the mic never opens between the two.
        speakWithBrowser(text);
        releaseRemote();
        releaseRemote = null;
        setIsPlaying(false);
        setIsSpeaking(false);
      }
    } catch (err) {
      const msg =
        err instanceof Error ? err.message : "TTS playback failed.";
      // Same hand-off: the fallback is speaking, so release after it holds.
      speakWithBrowser(text);
      releaseRemote?.();
      setError(msg);
      console.error("[useTTS]", err);
      setIsPlaying(false);
      setIsSpeaking(false);
    }
  }

  speakRef.current = speak;
  return { speak, isPlaying, error };
}

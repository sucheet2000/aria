"use client";

import { useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useAudioAmplitude } from "@/hooks/useAudioAmplitude";
import { ttsAudioRef } from "@/hooks/useTTS";

interface StatePalette {
  iris: string;
  acc: string;
  pulse: number;
}

export const STATE_PALETTES: Record<string, StatePalette> = {
  idle:       { iris: "#50b4ff", acc: "#2ef2cf", pulse: 0.3 },
  listening:  { iris: "#00d2ff", acc: "#00d2ff", pulse: 0.5 },
  thinking:   { iris: "#a064ff", acc: "#a064ff", pulse: 0.8 },
  speaking:   { iris: "#00ffb4", acc: "#00ffb4", pulse: 0.6 },
  happy:      { iris: "#ffd200", acc: "#ffd200", pulse: 0.4 },
  distressed: { iris: "#ff3c3c", acc: "#ff3c3c", pulse: 1.0 },
  fearful:    { iris: "#c864ff", acc: "#c864ff", pulse: 0.9 },
  surprised:  { iris: "#ffb400", acc: "#ffb400", pulse: 0.7 },
  neutral:    { iris: "#50b4ff", acc: "#2ef2cf", pulse: 0.3 },
};

// One canonical map from the emotion vocabulary to a visual state.
//
// The renderer used to index STATE_PALETTES directly and fall back to `idle`,
// which meant an emotion the table did not know about looked exactly like no
// emotion at all — "sad", "angry" and "disgusted" all rendered calm blue, with
// nothing to distinguish a gap in the table from a deliberate neutral.
//
// The groupings below reuse existing palettes rather than inventing colours:
// which distinct visual treatment each emotion deserves is a design decision,
// not one to make silently in a bug fix. What this does guarantee is that every
// emitted emotion resolves to a deliberate choice, and that adding a new one to
// the vocabulary without deciding its appearance fails a test instead of
// disappearing into the fallback.
export const EMOTION_PALETTE_KEY: Record<string, string> = {
  neutral: "neutral",
  happy: "happy",
  surprised: "surprised",
  fearful: "fearful",
  // Provisional groupings, pending design input:
  sad: "fearful",          // subdued, withdrawn
  angry: "distressed",     // high-arousal negative
  frustrated: "distressed",
  disgusted: "distressed",
  distressed: "distressed",
};

function getPalette(
  emotion: string,
  isThinking: boolean,
  isSpeaking: boolean,
  isListening: boolean,
): StatePalette {
  if (isSpeaking) return STATE_PALETTES.speaking;
  if (isThinking) return STATE_PALETTES.thinking;
  if (isListening) return STATE_PALETTES.listening;
  return STATE_PALETTES[EMOTION_PALETTE_KEY[emotion] ?? "idle"];
}

const MAX_JAW_PX = 13;

function lerp(a: number, b: number, r: number): number {
  return a + (b - a) * r;
}

export default function SkullAvatar() {
  const avatarEmotion = useAriaStore((s) => s.avatarEmotion);
  const isThinking = useAriaStore((s) => s.isThinking);
  const isSpeaking = useAriaStore((s) => s.isSpeaking);
  const isListening = useAriaStore((s) => s.isListening);

  const { amplitudeRef: ampRef, connectAudio } = useAudioAmplitude();

  const jawRef = useRef<SVGGElement>(null);
  const speakingRef = useRef(false);
  speakingRef.current = isSpeaking;

  const prefersReduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    if (!isSpeaking) return;
    const el = ttsAudioRef.current;
    if (!el) return;
    try {
      connectAudio(el);
    } catch {
      // analyser hookup is best-effort; phoneme fallback still animates the jaw
    }
  }, [isSpeaking, connectAudio]);

  useEffect(() => {
    let rafId: number;
    let jaw = 0;
    let speakPhase = 0;

    const tick = () => {
      if (speakingRef.current) {
        speakPhase += 0.17;
        const amp = ampRef.current;
        const target =
          amp > 0.01
            ? Math.min(1, amp * 4)
            : 0.42 * Math.abs(Math.sin(speakPhase * 1.8)) +
              0.3 * Math.abs(Math.sin(speakPhase * 3.1 + 1.0)) +
              0.28 * Math.abs(Math.sin(speakPhase * 0.7 + 2.2));
        jaw = lerp(jaw, target, 0.22);
      } else {
        jaw = lerp(jaw, 0, 0.1);
        speakPhase = 0;
      }
      if (jawRef.current) {
        jawRef.current.style.transform = `translateY(${(jaw * MAX_JAW_PX).toFixed(2)}px)`;
      }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
    // ampRef is a ref object with a stable identity; the amplitude VALUE is
    // read inside the loop, so the effect never re-runs on it.
  }, [ampRef]);

  const pal = getPalette(avatarEmotion, isThinking, isSpeaking, isListening);
  const pulseDur = `${(2.6 / Math.max(pal.pulse, 0.2)).toFixed(2)}s`;
  const bobClass = prefersReduced ? "" : "skullav-bob";
  const pulseClass = prefersReduced ? "" : "skullav-pulse";

  return (
    <div className="skullav-wrap">
      <style>{`
        .skullav-wrap { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
        .skullav-wrap svg { width: min(72vmin, 560px); height: auto; }
        .skullav-jaw { will-change: transform; }
        .skullav-bob { animation: skullav-bob 5.2s ease-in-out infinite; }
        .skullav-pulse { animation: skullav-pulse var(--skullav-pulse-dur, 2.6s) ease-in-out infinite; }
        @keyframes skullav-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(6px); } }
        @keyframes skullav-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
        @media (prefers-reduced-motion: reduce) {
          .skullav-bob, .skullav-pulse { animation: none; }
        }
      `}</style>
      <svg
        role="img"
        aria-label="ARIA — a cybernetic skull avatar with glowing eyes"
        viewBox="0 0 320 340"
        style={
          {
            "--skullav-iris": pal.iris,
            "--skullav-acc": pal.acc,
            "--skullav-pulse-dur": pulseDur,
          } as React.CSSProperties
        }
      >
        <defs>
          <filter id="skullav-glow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <filter id="skullav-glow-soft" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="2.5" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        <g className={bobClass}>
          {/* cranium cables */}
          <g fill="none" stroke="#6f68d8" strokeWidth="9" strokeLinecap="round">
            <path d="M120 52 C 96 20, 58 26, 52 62" />
            <path d="M148 40 C 140 12, 100 6, 84 30" />
            <path d="M204 44 C 224 16, 262 24, 266 58" />
          </g>
          <g fill="var(--skullav-acc, #2ef2cf)">
            <rect x="86" y="17" width="14" height="9" rx="2" transform="rotate(-18 93 21)" />
            <rect x="236" y="22" width="14" height="9" rx="2" transform="rotate(20 243 26)" />
            <rect x="60" y="40" width="12" height="8" rx="2" transform="rotate(-64 66 44)" />
          </g>

          {/* side machinery */}
          <g stroke="#241d54" strokeWidth="4">
            <rect x="14" y="140" width="52" height="58" rx="8" fill="#453ba3" />
            <rect x="22" y="150" width="36" height="10" rx="4" fill="var(--skullav-acc, #2ef2cf)" filter="url(#skullav-glow-soft)" />
            <circle cx="40" cy="180" r="8" fill="#5b52c4" />
            <rect x="252" y="118" width="56" height="16" rx="6" fill="#453ba3" />
            <rect x="292" y="112" width="14" height="28" rx="4" fill="#5b52c4" />
            <rect x="256" y="146" width="40" height="12" rx="5" fill="#5b52c4" />
            <circle cx="302" cy="152" r="7" fill="var(--skullav-acc, #2ef2cf)" filter="url(#skullav-glow-soft)" />
          </g>

          {/* neck tubes */}
          <g stroke="#241d54" strokeWidth="4">
            <rect x="126" y="300" width="14" height="34" rx="6" fill="#453ba3" />
            <rect x="146" y="304" width="14" height="34" rx="6" fill="#5b52c4" />
            <rect x="166" y="300" width="14" height="34" rx="6" fill="#453ba3" />
          </g>

          {/* skull upper */}
          <path
            d="M160 24 C 100 24, 62 66, 60 128 C 59 170, 74 194, 90 204 L 90 232
               C 90 246, 100 256, 114 260 L 206 260 C 220 256, 230 246, 230 232 L 230 204
               C 246 194, 261 170, 260 128 C 258 66, 220 24, 160 24 Z"
            fill="#7d76e2"
            stroke="#241d54"
            strokeWidth="6"
            strokeLinejoin="round"
          />
          {/* cel shading */}
          <path
            d="M232 62 C 252 88, 258 128, 252 156 C 248 176, 238 192, 230 200 L 230 226
               C 230 238, 222 248, 210 254 L 206 260 L 196 260 C 220 240, 232 200, 236 160
               C 240 116, 238 86, 232 62 Z"
            fill="#5b52c4"
            opacity="0.85"
          />
          <path d="M84 148 C 96 138, 128 134, 152 140 L 152 154 C 128 148, 100 150, 88 158 Z" fill="#5b52c4" opacity="0.7" />
          <path d="M168 140 C 192 134, 224 138, 236 148 L 232 158 C 220 150, 192 148, 168 154 Z" fill="#5b52c4" opacity="0.7" />

          {/* forehead plate */}
          <path
            d="M136 52 L 184 52 L 178 100 Q 160 112 142 100 Z"
            fill="#9d97b5"
            stroke="#241d54"
            strokeWidth="4"
            strokeLinejoin="round"
          />
          <circle cx="148" cy="66" r="4.5" fill="#ff7ce4" />
          <circle cx="160" cy="60" r="4.5" fill="#ff7ce4" />
          <circle cx="172" cy="66" r="4.5" fill="#ff7ce4" />
          <path d="M154 122 L 166 122 L 160 132 Z" fill="none" stroke="#241d54" strokeWidth="3" strokeLinejoin="round" />

          {/* eye sockets */}
          <path
            d="M84 168 C 88 152, 112 146, 130 152 C 146 158, 150 172, 144 184
               C 136 198, 112 202, 98 194 C 86 188, 82 178, 84 168 Z"
            fill="#221743"
            stroke="#241d54"
            strokeWidth="5"
          />
          <path
            d="M236 168 C 232 152, 208 146, 190 152 C 174 158, 170 172, 176 184
               C 184 198, 208 202, 222 194 C 234 188, 238 178, 236 168 Z"
            fill="#221743"
            stroke="#241d54"
            strokeWidth="5"
          />

          {/* cross eyes */}
          <g className={pulseClass} fill="var(--skullav-iris, #ff4ff0)" filter="url(#skullav-glow)">
            <g transform="rotate(-8 114 174)">
              <rect x="110" y="160" width="8" height="28" rx="3" />
              <rect x="100" y="170" width="28" height="8" rx="3" />
            </g>
            <g transform="rotate(8 206 174)">
              <rect x="202" y="160" width="8" height="28" rx="3" />
              <rect x="192" y="170" width="28" height="8" rx="3" />
            </g>
          </g>

          {/* nose */}
          <path
            d="M160 200 L 148 226 Q 160 234 172 226 Z"
            fill="#221743"
            stroke="#241d54"
            strokeWidth="4"
            strokeLinejoin="round"
          />

          {/* cheek vents */}
          <g fill="var(--skullav-acc, #2ef2cf)" opacity="0.9">
            <rect x="96" y="214" width="5" height="16" rx="2" transform="rotate(12 98 222)" />
            <rect x="106" y="216" width="5" height="16" rx="2" transform="rotate(12 108 224)" />
            <rect x="219" y="214" width="5" height="16" rx="2" transform="rotate(-12 221 222)" />
          </g>

          {/* upper teeth */}
          <g stroke="#241d54" strokeWidth="3.5">
            <path d="M112 240 L 208 240 L 208 262 L 112 262 Z" fill="#1c1440" />
            <rect x="114" y="240" width="14" height="20" rx="4" fill="#eecf56" />
            <rect x="130" y="240" width="14" height="23" rx="4" fill="#eecf56" />
            <rect x="146" y="240" width="13" height="21" rx="4" fill="#c9a53c" />
            <rect x="161" y="240" width="14" height="24" rx="4" fill="#eecf56" />
            <rect x="177" y="240" width="13" height="21" rx="4" fill="#eecf56" />
            <rect x="192" y="240" width="14" height="19" rx="4" fill="#c9a53c" />
          </g>

          {/* lower jaw — amplitude-driven */}
          <g ref={jawRef} className="skullav-jaw" data-testid="skull-jaw">
            <path
              d="M108 266 L 212 266 L 208 292 C 206 304, 196 312, 182 314 L 138 314
                 C 124 312, 114 304, 112 292 Z"
              fill="#7d76e2"
              stroke="#241d54"
              strokeWidth="6"
              strokeLinejoin="round"
            />
            <path
              d="M196 268 L 208 268 L 204 292 C 202 302, 194 309, 184 312 L 176 312
                 C 190 304, 196 288, 196 268 Z"
              fill="#5b52c4"
              opacity="0.8"
            />
            <g stroke="#241d54" strokeWidth="3">
              <rect x="122" y="266" width="12" height="15" rx="4" fill="#c9a53c" />
              <rect x="137" y="266" width="13" height="18" rx="4" fill="#eecf56" />
              <rect x="153" y="266" width="13" height="16" rx="4" fill="#eecf56" />
              <rect x="169" y="266" width="13" height="18" rx="4" fill="#eecf56" />
              <rect x="185" y="266" width="12" height="15" rx="4" fill="#c9a53c" />
            </g>
            <g fill="var(--skullav-acc, #2ef2cf)">
              <rect x="112" y="292" width="9" height="6" rx="2" transform="rotate(24 116 295)" />
              <rect x="200" y="290" width="9" height="6" rx="2" transform="rotate(-24 204 293)" />
            </g>
          </g>
        </g>
      </svg>
    </div>
  );
}

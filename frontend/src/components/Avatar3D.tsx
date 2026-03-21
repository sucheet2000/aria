"use client";

import { useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";

// --- Noise ---

function hash(n: number): number {
  const x = Math.sin(n) * 43758.5453123;
  return x - Math.floor(x);
}

function smoothNoise(x: number, y: number, z: number): number {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const iz = Math.floor(z);
  const fx = x - ix;
  const fy = y - iy;
  const fz = z - iz;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const uz = fz * fz * (3 - 2 * fz);

  const h00 = iy + hash(iz) * 57;
  const h01 = iy + hash(iz + 1) * 57;
  const h10 = iy + 1 + hash(iz) * 57;
  const h11 = iy + 1 + hash(iz + 1) * 57;

  const n000 = hash(ix + h00);
  const n100 = hash(ix + 1 + h00);
  const n010 = hash(ix + h10);
  const n110 = hash(ix + 1 + h10);
  const n001 = hash(ix + h01);
  const n101 = hash(ix + 1 + h01);
  const n011 = hash(ix + h11);
  const n111 = hash(ix + 1 + h11);

  const x00 = n000 + ux * (n100 - n000);
  const x10 = n010 + ux * (n110 - n010);
  const x01 = n001 + ux * (n101 - n001);
  const x11 = n011 + ux * (n111 - n011);
  const y0 = x00 + uy * (x10 - x00);
  const y1 = x01 + uy * (x11 - x01);
  return y0 + uz * (y1 - y0);
}

function fbm(x: number, y: number, z: number, oct: number): number {
  let v = 0;
  let a = 0.5;
  let f = 1;
  for (let i = 0; i < oct; i++) {
    v += a * smoothNoise(x * f, y * f, z * f);
    a *= 0.5;
    f *= 2.1;
  }
  return v;
}

// --- State definitions ---

type AvatarState = "idle" | "listening" | "thinking" | "speaking";

interface StateParams {
  hue: number;
  speed: number;
  turbulence: number;
  coreAlpha: number;
  strandCount: number;
  strandSpeed: number;
}

const STATE_PARAMS: Record<AvatarState, StateParams> = {
  idle: {
    hue: 250,
    speed: 0.4,
    turbulence: 0.3,
    coreAlpha: 0.6,
    strandCount: 5,
    strandSpeed: 0.3,
  },
  listening: {
    hue: 220,
    speed: 0.7,
    turbulence: 0.55,
    coreAlpha: 0.8,
    strandCount: 7,
    strandSpeed: 0.55,
  },
  thinking: {
    hue: 285,
    speed: 1.1,
    turbulence: 0.85,
    coreAlpha: 0.9,
    strandCount: 9,
    strandSpeed: 0.85,
  },
  speaking: {
    hue: 200,
    speed: 0.9,
    turbulence: 0.7,
    coreAlpha: 1.0,
    strandCount: 8,
    strandSpeed: 0.7,
  },
};

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

const LERP_RATE = 0.025;
const BASE_R = 110;
const CX = 160;
const CY = 160;

interface AnimState extends StateParams {
  t: number;
}

// --- Component ---

export default function Avatar3D() {
  const avatarEmotion = useAriaStore((s) => s.avatarEmotion);
  const isThinking = useAriaStore((s) => s.isThinking);
  const isSpeaking = useAriaStore((s) => s.isSpeaking);
  const wsConnected = useAriaStore((s) => s.wsConnected);
  const isListening = useAriaStore((s) => s.isListening);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  const animRef = useRef<AnimState>({
    t: 0,
    ...STATE_PARAMS.idle,
  });

  const reactiveRef = useRef({
    avatarEmotion,
    isThinking,
    isSpeaking,
    wsConnected,
    isListening,
    amplitude: 0,
  });

  useEffect(() => {
    reactiveRef.current.avatarEmotion = avatarEmotion;
  }, [avatarEmotion]);
  useEffect(() => {
    reactiveRef.current.isThinking = isThinking;
  }, [isThinking]);
  useEffect(() => {
    reactiveRef.current.isSpeaking = isSpeaking;
  }, [isSpeaking]);
  useEffect(() => {
    reactiveRef.current.wsConnected = wsConnected;
  }, [wsConnected]);
  useEffect(() => {
    reactiveRef.current.isListening = isListening;
  }, [isListening]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = 320 * dpr;
    canvas.height = 320 * dpr;
    canvas.style.width = "320px";
    canvas.style.height = "320px";

    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);

    function getTargetParams(): StateParams {
      const r = reactiveRef.current;

      let base: StateParams;
      if (!r.wsConnected) {
        base = {
          ...STATE_PARAMS.idle,
          coreAlpha: STATE_PARAMS.idle.coreAlpha * 0.4,
        };
      } else if (r.isSpeaking) {
        base = { ...STATE_PARAMS.speaking };
      } else if (r.isThinking) {
        base = { ...STATE_PARAMS.thinking };
      } else if (r.isListening) {
        base = { ...STATE_PARAMS.listening };
      } else {
        base = { ...STATE_PARAMS.idle };
      }

      const emotion = r.avatarEmotion;
      if (emotion === "happy" || emotion === "surprised") {
        base.hue += 20;
      } else if (emotion === "fearful" || emotion === "sad") {
        base.hue -= 20;
      } else if (emotion === "angry") {
        base.turbulence += 0.3;
      }

      return base;
    }

    function drawFrame(): void {
      if (!ctx) return;

      const target = getTargetParams();
      const s = animRef.current;
      const amp = reactiveRef.current.amplitude;

      s.hue = lerp(s.hue, target.hue, LERP_RATE);
      s.speed = lerp(s.speed, target.speed, LERP_RATE);
      s.turbulence = lerp(s.turbulence, target.turbulence, LERP_RATE);
      s.coreAlpha = lerp(s.coreAlpha, target.coreAlpha, LERP_RATE);
      s.strandCount = lerp(s.strandCount, target.strandCount, LERP_RATE);
      s.strandSpeed = lerp(s.strandSpeed, target.strandSpeed, LERP_RATE);

      s.t += 0.016 * s.speed;

      const { hue, turbulence, coreAlpha, strandCount, strandSpeed } = s;
      const t = s.t;
      const waveAmp = turbulence;

      ctx.clearRect(0, 0, 320, 320);

      // Ambient background bloom
      const bloom = ctx.createRadialGradient(CX, CY, 0, CX, CY, 160);
      bloom.addColorStop(0, `hsla(${hue},70%,30%,0.12)`);
      bloom.addColorStop(1, `hsla(${hue},70%,10%,0)`);
      ctx.fillStyle = bloom;
      ctx.fillRect(0, 0, 320, 320);

      // 4 outer glow layers
      for (let g = 0; g < 4; g++) {
        const gr = BASE_R + 10 + g * 8;
        const ga = 0.04 - g * 0.008;
        const gGrad = ctx.createRadialGradient(CX, CY, gr * 0.7, CX, CY, gr);
        gGrad.addColorStop(0, `hsla(${hue},80%,60%,${ga})`);
        gGrad.addColorStop(1, `hsla(${hue},80%,40%,0)`);
        ctx.fillStyle = gGrad;
        ctx.beginPath();
        ctx.arc(CX, CY, gr, 0, Math.PI * 2);
        ctx.fill();
      }

      // Blob outline (180 points)
      const BLOB_POINTS = 180;
      const pts: Array<[number, number]> = [];
      for (let i = 0; i < BLOB_POINTS; i++) {
        const a = (i / BLOB_POINTS) * Math.PI * 2;
        const n = fbm(Math.cos(a) * 0.8, Math.sin(a) * 0.8, t * 0.15, 3);
        const r = BASE_R + (n - 0.5) * waveAmp * 22;
        pts.push([CX + Math.cos(a) * r, CY + Math.sin(a) * r]);
      }

      const blobGrad = ctx.createRadialGradient(
        CX, CY * 0.85, BASE_R * 0.1,
        CX, CY, BASE_R * 1.1
      );
      blobGrad.addColorStop(0, `hsla(${hue + 30},90%,75%,0.9)`);
      blobGrad.addColorStop(0.4, `hsla(${hue},80%,50%,0.75)`);
      blobGrad.addColorStop(1, `hsla(${hue - 20},70%,25%,0.6)`);

      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < BLOB_POINTS; i++) {
        ctx.lineTo(pts[i][0], pts[i][1]);
      }
      ctx.closePath();
      ctx.fillStyle = blobGrad;
      ctx.fill();

      ctx.strokeStyle = `hsla(${hue + 40},100%,80%,0.3)`;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Internal flow lines (6 spiral lines)
      for (let fl = 0; fl < 6; fl++) {
        const flPhase = fl * ((Math.PI * 2) / 6) + t * 0.05;
        ctx.beginPath();
        for (let step = 0; step <= 40; step++) {
          const frac = step / 40;
          const fr = frac * BASE_R * 0.9;
          const angle =
            flPhase +
            frac * Math.PI * 3 +
            fbm(frac * 2 + fl, t * 0.1, fl * 0.3, 2) * 2;
          const px = CX + Math.cos(angle) * fr;
          const py = CY + Math.sin(angle) * fr;
          if (step === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.strokeStyle = `hsla(${hue + 20},80%,70%,0.06)`;
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }

      // Flow strands
      const strandInt = Math.round(strandCount);
      for (let si = 0; si < strandInt; si++) {
        const seed = si * 137.508;
        const phase = seed + t * strandSpeed * (0.8 + hash(seed) * 0.4);
        const lengthFrac = 0.5 + hash(seed * 1.3) * 0.45;
        const width = 1 + hash(seed * 2.1) * 1.5;
        const hueShift = (hash(seed * 3.7) - 0.5) * 40;

        const STRAND_STEPS = 30;
        ctx.beginPath();
        for (let sp = 0; sp <= STRAND_STEPS; sp++) {
          const frac = sp / STRAND_STEPS;
          const sr = frac * BASE_R * lengthFrac;
          const angle =
            phase +
            frac * Math.PI * 1.5 +
            fbm(
              frac * 2 + seed * 0.01,
              t * 0.12 + seed * 0.01,
              seed * 0.005,
              2
            ) * 2;
          const px = CX + Math.cos(angle) * sr;
          const py = CY + Math.sin(angle) * sr;
          if (sp === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.strokeStyle = `hsla(${hue + hueShift},90%,75%,0.4)`;
        ctx.lineWidth = width;
        ctx.stroke();

        // Tip droplet
        const tipAngle =
          phase +
          Math.PI * 1.5 +
          fbm(2 + seed * 0.01, t * 0.12 + seed * 0.01, seed * 0.005, 2) * 2;
        const tipR = BASE_R * lengthFrac;
        ctx.beginPath();
        ctx.arc(
          CX + Math.cos(tipAngle) * tipR,
          CY + Math.sin(tipAngle) * tipR,
          width * 0.8,
          0,
          Math.PI * 2
        );
        ctx.fillStyle = `hsla(${hue + hueShift},100%,85%,0.5)`;
        ctx.fill();
      }

      // Core
      const coreSize = 28 + amp * 20;
      const corePulse = 1 + Math.sin(t * 3.5) * 0.12 * coreAlpha;

      const coreGlow = ctx.createRadialGradient(
        CX, CY, 0,
        CX, CY, coreSize * 3.5
      );
      coreGlow.addColorStop(0, `hsla(${hue + 20},100%,80%,${coreAlpha * 0.25})`);
      coreGlow.addColorStop(1, `hsla(${hue},80%,50%,0)`);
      ctx.fillStyle = coreGlow;
      ctx.beginPath();
      ctx.arc(CX, CY, coreSize * 3.5, 0, Math.PI * 2);
      ctx.fill();

      const innerCore = ctx.createRadialGradient(
        CX, CY, 0,
        CX, CY, coreSize * corePulse
      );
      innerCore.addColorStop(0, `hsla(${hue + 40},100%,95%,${coreAlpha})`);
      innerCore.addColorStop(0.5, `hsla(${hue + 20},90%,75%,${coreAlpha * 0.7})`);
      innerCore.addColorStop(1, `hsla(${hue},80%,55%,0)`);
      ctx.fillStyle = innerCore;
      ctx.beginPath();
      ctx.arc(CX, CY, coreSize * corePulse, 0, Math.PI * 2);
      ctx.fill();

      // Specular highlight
      const specX = CX - coreSize * 0.3;
      const specY = CY - coreSize * 0.3;
      const spec = ctx.createRadialGradient(
        specX, specY, 0,
        specX, specY, coreSize * 0.5
      );
      spec.addColorStop(0, `rgba(255,255,255,${coreAlpha * 0.6})`);
      spec.addColorStop(1, `rgba(255,255,255,0)`);
      ctx.fillStyle = spec;
      ctx.beginPath();
      ctx.arc(specX, specY, coreSize * 0.5, 0, Math.PI * 2);
      ctx.fill();
    }

    function loop(): void {
      drawFrame();
      rafRef.current = requestAnimationFrame(loop);
    }

    rafRef.current = requestAnimationFrame(loop);

    return () => {
      cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return <canvas ref={canvasRef} style={{ display: "block" }} />;
}

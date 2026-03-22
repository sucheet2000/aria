"use client";

import { useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useAudioAmplitude } from "@/hooks/useAudioAmplitude";
import { ttsAudioRef } from "@/hooks/useTTS";

// --- Types ---

interface RGB { r: number; g: number; b: number; }
interface StateProfile {
  h1: RGB;
  h2: RGB;
  eye: RGB;
  lightX: number;
  lightY: number;
  pulse: number;
  speaking: boolean;
}

interface FloatNode {
  x: number;
  y: number;
  vx: number;
  vy: number;
  size: number;
  _a: number;
  _r: number;
}

// --- State profiles ---

const PROFILES: Record<string, StateProfile> = {
  idle: {
    h1:{r:180,g:220,b:255}, h2:{r:20,g:60,b:120},
    eye:{r:80,g:180,b:255}, lightX:0, lightY:-1, pulse:0.3, speaking:false,
  },
  listening: {
    h1:{r:100,g:220,b:255}, h2:{r:10,g:80,b:140},
    eye:{r:0,g:210,b:255}, lightX:0.2, lightY:-0.9, pulse:0.5, speaking:false,
  },
  thinking: {
    h1:{r:160,g:140,b:255}, h2:{r:40,g:20,b:120},
    eye:{r:160,g:100,b:255}, lightX:-0.2, lightY:-1, pulse:0.8, speaking:false,
  },
  speaking: {
    h1:{r:160,g:255,b:220}, h2:{r:10,g:100,b:80},
    eye:{r:0,g:255,b:180}, lightX:0, lightY:-0.8, pulse:0.6, speaking:true,
  },
  distressed: {
    h1:{r:255,g:160,b:160}, h2:{r:120,g:20,b:20},
    eye:{r:255,g:60,b:60}, lightX:0.3, lightY:-0.7, pulse:1.0, speaking:false,
  },
  happy: {
    h1:{r:255,g:240,b:160}, h2:{r:120,g:80,b:10},
    eye:{r:255,g:210,b:0}, lightX:0, lightY:-1.1, pulse:0.4, speaking:false,
  },
  fearful: {
    h1:{r:200,g:160,b:255}, h2:{r:60,g:20,b:100},
    eye:{r:200,g:100,b:255}, lightX:0.2, lightY:-0.8, pulse:0.9, speaking:false,
  },
  surprised: {
    h1:{r:255,g:220,b:100}, h2:{r:100,g:70,b:10},
    eye:{r:255,g:180,b:0}, lightX:0, lightY:-1.2, pulse:0.7, speaking:false,
  },
  neutral: {
    h1:{r:180,g:220,b:255}, h2:{r:20,g:60,b:120},
    eye:{r:80,g:180,b:255}, lightX:0, lightY:-1, pulse:0.3, speaking:false,
  },
};

function getProfile(
  emotion: string,
  isThinking: boolean,
  isSpeaking: boolean,
  isListening: boolean,
): StateProfile {
  if (isSpeaking) return PROFILES.speaking;
  if (isThinking) return PROFILES.thinking;
  if (isListening) return PROFILES.listening;
  return PROFILES[emotion] ?? PROFILES.idle;
}

// --- Geometry ---
// V3: [x, y, z] — x,y in [0,1] normalized, z for lighting (-1=recessed, 1=front)

const V3: [number,number,number][] = [
  // 0-4 skull top
  [.50,-.04,.10],[.20,.03,.00],[.80,.03,.00],[.08,.17,-.20],[.92,.17,-.20],
  // 5-9 upper skull
  [.27,.09,.20],[.73,.09,.20],[.50,.07,.50],[.16,.24,.10],[.84,.24,.10],
  // 10-15 forehead/brow
  [.31,.21,.60],[.69,.21,.60],[.50,.19,.70],[.21,.31,.30],[.79,.31,.30],[.50,.29,.80],
  // 16-21 eye sockets
  [.29,.27,-.30],[.71,.27,-.30],[.37,.25,-.10],[.63,.25,-.10],[.35,.33,-.40],[.65,.33,-.40],
  // 22-27 nose
  [.50,.27,.90],[.43,.41,.70],[.57,.41,.70],[.45,.49,.60],[.55,.49,.60],[.50,.53,.80],
  // 28-33 cheeks
  [.14,.43,.20],[.86,.43,.20],[.24,.39,.50],[.76,.39,.50],[.21,.53,.30],[.79,.53,.30],
  // 34-39 upper mouth region
  [.34,.585,.40],[.66,.585,.40],[.41,.565,.50],[.59,.565,.50],[.50,.555,.55],[.50,.625,-.10],
  // 40-45 jaw/chin
  [.29,.645,.30],[.71,.645,.30],[.17,.705,.00],[.83,.705,.00],[.37,.745,.40],[.63,.745,.40],
  // 46-50 chin bottom
  [.50,.705,.55],[.27,.805,.10],[.73,.805,.10],[.50,.865,.25],[.50,.955,.00],
  // 51-60 mouth mesh
  [.335,.600,.35],  // 51 left corner
  [.665,.600,.35],  // 52 right corner
  [.400,.582,.50],  // 53 upper lip left
  [.500,.575,.55],  // 54 upper lip center
  [.600,.582,.50],  // 55 upper lip right
  [.390,.618,.40],  // 56 lower lip left  (jaw-driven)
  [.500,.628,.45],  // 57 lower lip center (jaw-driven)
  [.610,.618,.40],  // 58 lower lip right  (jaw-driven)
  [.500,.590,-.20], // 59 inner upper (dark)
  [.500,.610,-.30], // 60 inner lower (dark, jaw-driven)
];

const FACE_TRIS: number[][] = [
  [0,1,5],[0,5,7],[0,7,6],[0,6,2],[1,3,5],[2,6,4],[3,8,5],[4,6,9],
  [5,7,10],[6,7,11],[7,10,12],[7,11,12],[7,12,15],
  [8,10,13],[9,11,14],[10,12,13],[11,12,14],
  [13,16,10],[14,17,11],[10,16,18],[11,17,19],[12,15,22],[15,12,13],[15,12,14],
  [13,16,20],[16,18,20],[18,20,23],  // left eye socket (indices 24,25,26)
  [14,17,21],[17,19,21],[19,21,24],  // right eye socket (indices 27,28,29)
  [12,22,15],[22,23,27],[22,24,27],[23,25,27],[24,26,27],
  [13,28,30],[14,29,31],[8,28,13],[9,29,14],
  [28,30,32],[29,31,33],[30,32,34],[31,33,35],
  [20,23,30],[21,24,31],[23,25,30],[24,26,31],
  [25,27,36],[26,27,37],[25,36,34],[26,37,35],
  [34,36,38],[35,37,38],[34,38,51],[35,38,52],
  [34,40,39],[35,41,39],[40,42,47],[41,43,48],
  [40,44,47],[41,45,48],
  [44,46,49],[45,46,49],[46,47,49],[46,48,49],[49,50,47],[49,50,48],
];

// Eye socket triangle indices in FACE_TRIS (0-based)
const EYE_TRI_INDICES = new Set([24,25,26,27,28,29]);

const MOUTH_TRIS: number[][] = [
  [51,53,54],[51,54,52],[52,54,55],   // upper lip (0,1,2)
  [51,56,57],[51,57,52],[52,57,58],   // lower lip (3,4,5)
  [53,59,54],[54,59,55],              // inner upper dark (6,7)
  [56,60,57],[57,60,58],              // inner lower dark (8,9)
  [59,60,54],[54,60,57],              // center dark (10,11)
];

const MOUTH_DARK = new Set([6,7,8,9,10,11]);

// --- Math helpers ---

function lerpN(a: number, b: number, r: number): number { return a + (b - a) * r; }
function lerpRGB(a: RGB, b: RGB, r: number): RGB {
  return { r: lerpN(a.r, b.r, r), g: lerpN(a.g, b.g, r), b: lerpN(a.b, b.b, r) };
}

function faceLight(tri: number[], lx: number, ly: number, lz = 0.8): number {
  const [a,b,c] = tri.map(i => V3[i]);
  if (!a || !b || !c) return 0.5;
  const ab = [b[0]-a[0], b[1]-a[1], b[2]-a[2]];
  const ac = [c[0]-a[0], c[1]-a[1], c[2]-a[2]];
  const nx = ab[1]*ac[2] - ab[2]*ac[1];
  const ny = ab[2]*ac[0] - ab[0]*ac[2];
  const nz = ab[0]*ac[1] - ab[1]*ac[0];
  const len = Math.sqrt(nx*nx + ny*ny + nz*nz) || 1;
  return Math.max(0, (nx/len)*lx + (ny/len)*(-ly) + (nz/len)*lz);
}

function avgZ(tri: number[]): number {
  return tri.reduce((s, i) => s + (V3[i]?.[2] ?? 0), 0) / tri.length;
}

// --- Main component ---

export default function Avatar3D() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const avatarEmotion     = useAriaStore(s => s.avatarEmotion);
  const isThinking        = useAriaStore(s => s.isThinking);
  const isSpeaking        = useAriaStore(s => s.isSpeaking);
  const isListening       = useAriaStore(s => s.isListening);
  const symbolicInference = useAriaStore(s => s.symbolicInference);
  const wsConnected       = useAriaStore(s => s.wsConnected);

  const { amplitude } = useAudioAmplitude();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    // Capture non-null references for use in closures
    const cvs: HTMLCanvasElement = canvas;
    const gfx: CanvasRenderingContext2D = ctx;

    let rafId: number;
    let t = 0;
    let speakPhase = 0;

    // Mutable lerp state
    const cur = {
      h1: { ...PROFILES.idle.h1 },
      h2: { ...PROFILES.idle.h2 },
      eye: { ...PROFILES.idle.eye },
      lightX: 0,
      lightY: -1,
      pulse: 0.3,
      jaw: 0,
    };

    // Floating scan nodes
    const nodes: FloatNode[] = Array.from({length:18}, () => {
      const a = Math.random() * Math.PI * 2;
      const r = 195 + Math.random() * 110;
      return {
        x: 0,
        y: 0,
        vx: (Math.random() - 0.5) * 0.28,
        vy: (Math.random() - 0.5) * 0.18,
        size: 1.5 + Math.random() * 2,
        _a: a,
        _r: r,
      };
    });

    let W = 600, H = 620;
    let EYE_L: [number,number] = [0,0];
    let EYE_R: [number,number] = [0,0];
    const EYE_W = 36, EYE_H = 15;

    function sc(x: number, y: number): [number, number] {
      const padX = W * 0.22;
      const padY = H * 0.10;
      return [padX + x * (W - padX*2), padY + y * (H - padY*2)];
    }

    function getV2(jaw: number): [number,number][] {
      return V3.map(([x,y], i) => {
        let dy = 0;
        if (i === 56) dy = jaw * 22;
        if (i === 57) dy = jaw * 30;
        if (i === 58) dy = jaw * 22;
        if (i === 60) dy = jaw * 18;
        const [px, py] = sc(x, y);
        return [px, py + dy];
      });
    }

    function applyResize() {
      const dpr = window.devicePixelRatio || 1;
      W = cvs.offsetWidth || 600;
      H = cvs.offsetHeight || 620;
      cvs.width = W * dpr;
      cvs.height = H * dpr;
      gfx.setTransform(1,0,0,1,0,0);
      gfx.scale(dpr, dpr);
      EYE_L = sc(0.34, 0.305);
      EYE_R = sc(0.66, 0.305);

      nodes.forEach(n => {
        if (n.x === 0) {
          n.x = W/2 + Math.cos(n._a) * n._r * (W/560);
          n.y = H/2 + Math.sin(n._a) * n._r * 0.7 * (H/620) - H*0.06;
        }
      });
    }

    const ro = new ResizeObserver(applyResize);
    ro.observe(cvs);
    applyResize();

    function brackets(): [number,number][][] {
      const ml = W*0.16, mr = W*0.84, mt = H*0.10, mb = H*0.84, bl = 38;
      return [
        [[ml,mt],[ml+bl,mt],[ml,mt+bl]],
        [[mr,mt],[mr-bl,mt],[mr,mt+bl]],
        [[ml,mb],[ml+bl,mb],[ml,mb-bl]],
        [[mr,mb],[mr-bl,mb],[mr,mb-bl]],
      ];
    }

    function drawEyes(eye: RGB) {
      const eyePulse = 0.75 + 0.25 * Math.sin(t * 2.2);
      for (const [ex, ey] of [EYE_L, EYE_R]) {
        gfx.beginPath();
        gfx.ellipse(ex, ey, EYE_W, EYE_H, 0, 0, Math.PI*2);
        gfx.fillStyle = "rgba(2,4,12,0.95)";
        gfx.fill();

        const iris = gfx.createRadialGradient(ex, ey, 0, ex, ey, EYE_H*1.1);
        iris.addColorStop(0, `rgba(${eye.r},${eye.g},${eye.b},${0.95*eyePulse})`);
        iris.addColorStop(0.5, `rgba(${eye.r},${eye.g},${eye.b},${0.55*eyePulse})`);
        iris.addColorStop(1, `rgba(${eye.r},${eye.g},${eye.b},0)`);
        gfx.beginPath();
        gfx.ellipse(ex, ey, EYE_W*0.9, EYE_H*0.9, 0, 0, Math.PI*2);
        gfx.fillStyle = iris;
        gfx.fill();

        gfx.beginPath();
        gfx.arc(ex, ey, 4, 0, Math.PI*2);
        gfx.fillStyle = `rgba(${Math.min(255,eye.r+80)},${Math.min(255,eye.g+80)},${Math.min(255,eye.b+80)},${eyePulse})`;
        gfx.fill();

        gfx.beginPath();
        gfx.arc(ex-7, ey-4, 2.5, 0, Math.PI*2);
        gfx.fillStyle = `rgba(255,255,255,${0.5*eyePulse})`;
        gfx.fill();
      }
    }

    function frame() {
      t += 0.016;

      const profile = getProfile(avatarEmotion, isThinking, isSpeaking, isListening);
      const tgt = profile;

      cur.h1 = lerpRGB(cur.h1, tgt.h1, 0.03);
      cur.h2 = lerpRGB(cur.h2, tgt.h2, 0.03);
      cur.eye = lerpRGB(cur.eye, tgt.eye, 0.04);
      cur.lightX = lerpN(cur.lightX, tgt.lightX, 0.03);
      cur.lightY = lerpN(cur.lightY, tgt.lightY, 0.03);
      cur.pulse = lerpN(cur.pulse, tgt.pulse, 0.03);

      // Jaw: driven by amplitude when speaking, else phoneme sim closes to 0
      if (tgt.speaking) {
        speakPhase += 0.17;
        const ampJaw = amplitude > 0.01 ? Math.min(1, amplitude * 4) : (
          0.42*Math.abs(Math.sin(speakPhase*1.8)) +
          0.30*Math.abs(Math.sin(speakPhase*3.1+1.0)) +
          0.28*Math.abs(Math.sin(speakPhase*0.7+2.2))
        );
        cur.jaw = lerpN(cur.jaw, ampJaw, 0.22);
      } else {
        cur.jaw = lerpN(cur.jaw, 0, 0.10);
        speakPhase = 0;
      }

      const V2 = getV2(cur.jaw);
      const { h1, h2, eye, lightX, lightY } = cur;
      const facePulse = 0.85 + 0.15*Math.sin(t*2)*cur.pulse;

      // Background
      const bg = gfx.createRadialGradient(W/2, H/2-40, 40, W/2, H/2, Math.max(W,H)*0.55);
      bg.addColorStop(0, `rgb(${Math.floor(h2.r*0.4+8)},${Math.floor(h2.g*0.3+20)},${Math.floor(h2.b*0.4+50)})`);
      bg.addColorStop(1, "#060e1c");
      gfx.fillStyle = bg;
      gfx.fillRect(0, 0, W, H);

      // Floating nodes
      for (const n of nodes) {
        n.x += n.vx; n.y += n.vy;
        if (n.x < 40 || n.x > W-40) n.vx *= -1;
        if (n.y < 40 || n.y > H-40) n.vy *= -1;
      }
      gfx.strokeStyle = `rgba(${h1.r},${h1.g},${h1.b},0.14)`;
      gfx.lineWidth = 0.5;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i+1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
          if (dx*dx + dy*dy < 14000) {
            gfx.beginPath();
            gfx.moveTo(nodes[i].x, nodes[i].y);
            gfx.lineTo(nodes[j].x, nodes[j].y);
            gfx.stroke();
          }
        }
      }
      for (const n of nodes) {
        gfx.beginPath();
        gfx.arc(n.x, n.y, n.size, 0, Math.PI*2);
        gfx.fillStyle = `rgba(${h1.r},${h1.g},${h1.b},0.5)`;
        gfx.fill();
      }

      // HUD brackets
      gfx.strokeStyle = `rgba(${h1.r},${h1.g},${h1.b},0.6)`;
      gfx.lineWidth = 1.5;
      for (const [corner, ...lines] of brackets()) {
        gfx.beginPath();
        gfx.moveTo(lines[0][0], lines[0][1]);
        gfx.lineTo(corner[0], corner[1]);
        gfx.lineTo(lines[1][0], lines[1][1]);
        gfx.stroke();
      }

      // Sort all tris painter's order
      type TriEntry = { tri: number[]; idx: number; z: number; type: "face"|"mouth"; };
      const allTris: TriEntry[] = [
        ...FACE_TRIS.map((tri, idx) => ({ tri, idx, z: avgZ(tri), type: "face" as const })),
        ...MOUTH_TRIS.map((tri, idx) => ({ tri, idx, z: avgZ(tri), type: "mouth" as const })),
      ].sort((a, b) => a.z - b.z);

      for (const { tri, idx, type } of allTris) {
        if (type === "face" && EYE_TRI_INDICES.has(idx)) continue;
        const pts = tri.map(i => V2[i]);
        if (pts.some(p => !p)) continue;

        gfx.beginPath();
        gfx.moveTo(pts[0][0], pts[0][1]);
        gfx.lineTo(pts[1][0], pts[1][1]);
        gfx.lineTo(pts[2][0], pts[2][1]);
        gfx.closePath();

        if (type === "mouth" && MOUTH_DARK.has(idx)) {
          gfx.fillStyle = `rgba(1,3,${Math.floor(10+cur.jaw*8)},${0.97-cur.jaw*0.1})`;
        } else if (type === "mouth") {
          const light = faceLight(tri, lightX, lightY) * facePulse * (1 + cur.jaw*0.15);
          const boost = 0.08;
          gfx.fillStyle = `rgb(${Math.min(255,Math.floor(lerpN(h2.r,h1.r,Math.min(1,light+boost))))},${Math.min(255,Math.floor(lerpN(h2.g,h1.g,Math.min(1,light+boost))))},${Math.min(255,Math.floor(lerpN(h2.b,h1.b,Math.min(1,light+boost))))})`;
        } else {
          const light = faceLight(tri, lightX, lightY) * facePulse;
          gfx.fillStyle = `rgb(${Math.floor(lerpN(h2.r,h1.r,light))},${Math.floor(lerpN(h2.g,h1.g,light))},${Math.floor(lerpN(h2.b,h1.b,light))})`;
        }
        gfx.fill();
        gfx.strokeStyle = `rgba(${h1.r},${h1.g},${h1.b},0.09)`;
        gfx.lineWidth = 0.6;
        gfx.stroke();
      }

      // Eyes on top
      drawEyes(eye);

      // Scanline for thinking/listening
      if (isThinking || isListening) {
        const sy = (t * 55) % H;
        gfx.fillStyle = `rgba(${h1.r},${h1.g},${h1.b},0.04)`;
        gfx.fillRect(0, sy, W, 3);
      }

      // Symbolic inference text below face
      if (symbolicInference) {
        gfx.font = `300 12px var(--font-display, sans-serif)`;
        gfx.fillStyle = `rgba(${h1.r},${h1.g},${h1.b},0.45)`;
        gfx.textAlign = "center";
        gfx.fillText(
          symbolicInference.length > 80 ? symbolicInference.slice(0,80)+"..." : symbolicInference,
          W/2, H - 18,
        );
        gfx.textAlign = "start";
      }

      rafId = requestAnimationFrame(frame);
    }

    rafId = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(rafId);
      ro.disconnect();
    };
  }, [avatarEmotion, isThinking, isSpeaking, isListening, symbolicInference, wsConnected, amplitude]);

  return (
    <div style={{ position:"relative", width:"100%", height:"100%" }}>
      <canvas
        ref={canvasRef}
        style={{ display:"block", width:"100%", height:"100%" }}
      />
    </div>
  );
}

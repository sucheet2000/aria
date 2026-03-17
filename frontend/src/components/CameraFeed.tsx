"use client";

import { useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCamera } from "@/hooks/useCamera";

export default function CameraFeed() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);

  const wsConnected = useAriaStore((s) => s.wsConnected);
  const { isActive, error } = useCamera(videoRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    function draw() {
      if (!canvas || !video) return;

      const w = video.clientWidth;
      const h = video.clientHeight;

      if (w === 0 || h === 0) {
        rafRef.current = requestAnimationFrame(draw);
        return;
      }

      if (canvas.width !== w) canvas.width = w;
      if (canvas.height !== h) canvas.height = h;

      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const { faceLandmarks, handLandmarks } = useAriaStore.getState();

      if (faceLandmarks.length > 0) {
        ctx.fillStyle = "rgba(99, 179, 237, 0.6)";
        const count = Math.min(faceLandmarks.length, 468);
        for (let i = 0; i < count; i++) {
          const point = faceLandmarks[i];
          if (!point) continue;
          ctx.beginPath();
          ctx.arc(point[0] * canvas.width, point[1] * canvas.height, 1, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      if (handLandmarks.length > 0) {
        ctx.fillStyle = "rgba(154, 230, 180, 0.8)";
        for (const point of handLandmarks) {
          if (!point) continue;
          ctx.beginPath();
          ctx.arc(point[0] * canvas.width, point[1] * canvas.height, 3, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    }

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  return (
    <div className="w-full rounded-lg border border-aria-border bg-aria-surface overflow-hidden">
      <div className="relative" style={{ transform: "scaleX(-1)" }}>
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className="w-full block"
        />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full pointer-events-none"
        />
      </div>
      <div className="flex items-center justify-between px-3 py-2 text-xs">
        <span className="text-aria-muted">
          {error ? error : isActive ? "camera active" : "camera inactive"}
        </span>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${wsConnected ? "bg-green-400" : "bg-red-400"}`}
          />
        </div>
      </div>
    </div>
  );
}

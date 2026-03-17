"use client";

import { useEffect, useRef } from "react";
import { useAriaStore } from "@/store/ariaStore";
import { useCamera } from "@/hooks/useCamera";

export default function CameraFeed() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const { wsConnected } = useAriaStore();
  const { stream, error, startCamera } = useCamera();

  useEffect(() => {
    startCamera();
  }, [startCamera]);

  useEffect(() => {
    if (stream && videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  return (
    <div className="relative flex-1 overflow-hidden rounded-2xl border border-aria-accent/20 bg-aria-surface">
      {error ? (
        <div className="flex h-full items-center justify-center text-sm text-red-400">
          Camera error: {error}
        </div>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className="h-full w-full object-cover"
        />
      )}
      <canvas ref={canvasRef} className="hidden" />

      <div className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-full bg-black/50 px-2.5 py-1 text-xs">
        <span
          className={`h-1.5 w-1.5 rounded-full ${wsConnected ? "bg-green-400" : "bg-red-400"}`}
        />
        <span className="text-slate-300">{wsConnected ? "Connected" : "Disconnected"}</span>
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface AudioAmplitudeHook {
  amplitude: number;
  connectAudio: (audioElement: HTMLAudioElement) => void;
}

export function useAudioAmplitude(): AudioAmplitudeHook {
  const [amplitude, setAmplitude] = useState(0);

  const contextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null);
  const dataRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(0) as Uint8Array<ArrayBuffer>);
  const rafRef = useRef<number>(0);

  const connectAudio = useCallback((audioElement: HTMLAudioElement): void => {
    if (!contextRef.current) {
      contextRef.current = new AudioContext();
      const analyser = contextRef.current.createAnalyser();
      analyser.fftSize = 256;
      analyserRef.current = analyser;
      dataRef.current = new Uint8Array(analyser.frequencyBinCount) as Uint8Array<ArrayBuffer>;
      analyser.connect(contextRef.current.destination);
    }

    const ctx = contextRef.current;
    if (ctx.state === "suspended") {
      ctx.resume();
    }

    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect();
      } catch {
        // ignore
      }
    }

    const source = ctx.createMediaElementSource(audioElement);
    sourceRef.current = source;
    source.connect(analyserRef.current!);

    cancelAnimationFrame(rafRef.current);

    function tick(): void {
      if (!analyserRef.current) return;
      analyserRef.current.getByteFrequencyData(dataRef.current);
      let sum = 0;
      for (let i = 0; i < dataRef.current.length; i++) {
        sum += dataRef.current[i];
      }
      setAmplitude(sum / dataRef.current.length / 255);
      rafRef.current = requestAnimationFrame(tick);
    }

    rafRef.current = requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    return () => {
      cancelAnimationFrame(rafRef.current);
      if (contextRef.current) {
        contextRef.current.close();
      }
    };
  }, []);

  return { amplitude, connectAudio };
}

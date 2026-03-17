import { RefObject, useEffect, useRef, useState } from "react";

interface UseCameraResult {
  stream: MediaStream | null;
  error: string | null;
  isActive: boolean;
  stopCamera: () => void;
}

export function useCamera(videoRef: RefObject<HTMLVideoElement>): UseCameraResult {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isActive, setIsActive] = useState(false);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function startCamera() {
      try {
        const mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { width: 1280, height: 720, facingMode: "user" },
          audio: false,
        });
        if (cancelled) {
          mediaStream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = mediaStream;
        setStream(mediaStream);
        setIsActive(true);
        setError(null);
        if (videoRef.current) {
          videoRef.current.srcObject = mediaStream;
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof Error && err.name === "NotAllowedError") {
          setError("Camera permission denied");
        } else {
          setError(err instanceof Error ? err.message : "Camera access failed");
        }
      }
    }

    startCamera();

    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [videoRef]);

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    setIsActive(false);
  }

  return { stream, error, isActive, stopCamera };
}

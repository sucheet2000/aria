"use client";

import { useEffect, useRef, useState } from "react";
import {
  FaceLandmarker,
  FilesetResolver,
  HandLandmarker,
} from "@mediapipe/tasks-vision";
import { useAriaStore } from "@/store/ariaStore";
import type { PerceptionFrame } from "@/store/ariaStore";
import { abortCognitionRef } from "@/hooks/useCognition";
import { visionCaptureActiveRef } from "@/hooks/visionCaptureState";
import { EmotionClassifier } from "@/lib/perception/emotion";
import { GestureClassifier, gestureName } from "@/lib/perception/gesture";
import { headPoseFromMatrix } from "@/lib/perception/headPose";

// MediaPipe WASM + models load from the official CDN (jsDelivr for the WASM
// runtime pinned to the installed @mediapipe/tasks-vision version; Google Cloud
// Storage for the float16/1 .task models). Same-origin provisioning did not work
// on Vercel — the large binaries 404 — so we use the vendor CDN directly.
const WASM_PATH =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const FACE_MODEL_PATH =
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const HAND_MODEL_PATH =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
const TARGET_FPS = 15;
const FRAME_INTERVAL_MS = 1000 / TARGET_FPS;
const FACE_ABSENCE_THRESHOLD_S = 0.5;

export interface UseVisionCaptureResult {
  active: boolean;
  loading: boolean;
  error: string | null;
}

// Browser port of vision_worker.FaceExitDetector: fires once when the face has
// been absent for the threshold after having been seen.
class FaceExitDetector {
  private lastFaceTime: number;
  private wasDetected = false;
  private interruptSent = false;

  constructor(nowSec: number) {
    this.lastFaceTime = nowSec;
  }

  update(faceDetected: boolean, nowSec: number): boolean {
    if (faceDetected) {
      this.lastFaceTime = nowSec;
      this.wasDetected = true;
      this.interruptSent = false;
      return false;
    }
    if (this.wasDetected && !this.interruptSent) {
      if (nowSec - this.lastFaceTime >= FACE_ABSENCE_THRESHOLD_S) {
        this.interruptSent = true;
        return true;
      }
    }
    return false;
  }
}

function round4(v: number): number {
  return Math.round(v * 1e4) / 1e4;
}

function mapErrorMessage(err: unknown): string {
  if (err instanceof Error) {
    if (err.name === "NotAllowedError" || err.name === "SecurityError") {
      return "Camera permission denied";
    }
    if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
      return "No camera found";
    }
    if (err.name === "NotReadableError") {
      return "Camera is in use by another application";
    }
    return err.message || "Vision capture failed";
  }
  return "Vision capture failed";
}

export function useVisionCapture(enabled: boolean): UseVisionCaptureResult {
  const [active, setActive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    let rafId = 0;
    let lastFrameTime = 0;
    let stream: MediaStream | null = null;
    let video: HTMLVideoElement | null = null;
    let faceLandmarker: FaceLandmarker | null = null;
    let handLandmarker: HandLandmarker | null = null;
    // Model creation is async, so an unmount can land while landmarkers are
    // still being built. Cleanup would then run against variables that are
    // still null and close nothing, and the awaits would resolve into a dead
    // closure — stranding two MediaPipe instances and their WASM memory for
    // the life of the page, once per camera toggle. Every post-await
    // cancellation check therefore routes through here, and so does cleanup.
    // Safe to call repeatedly: each resource is released and nulled, so a
    // second call is a no-op and a resource created AFTER an earlier call is
    // still released by the next one.
    function dispose(): void {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = 0;
      stream?.getTracks().forEach((t) => t.stop());
      stream = null;
      if (video) video.srcObject = null;
      video = null;
      faceLandmarker?.close();
      faceLandmarker = null;
      handLandmarker?.close();
      handLandmarker = null;
    }

    const emotionClassifier = new EmotionClassifier();
    const gestureClassifier = new GestureClassifier();
    const faceExit = new FaceExitDetector(performance.now() / 1000);

    function processFrame(): void {
      rafId = requestAnimationFrame(processFrame);
      if (cancelled || !video || !faceLandmarker || !handLandmarker) return;

      const now = performance.now();
      if (now - lastFrameTime < FRAME_INTERVAL_MS) return;
      lastFrameTime = now;

      if (video.readyState < 2 || video.videoWidth === 0) return;

      const faceResult = faceLandmarker.detectForVideo(video, now);
      const handResult = handLandmarker.detectForVideo(video, now);

      const faceDetected = faceResult.faceLandmarks.length > 0;
      let faceLandmarks: number[][] = [];
      let headPose = { pitch: 0, yaw: 0, roll: 0 };
      let emotion = "neutral";
      let emotionConfidence = 0;

      if (faceDetected) {
        const lm = faceResult.faceLandmarks[0];
        const faceFull = lm.map((p) => [p.x, p.y, p.z]);
        faceLandmarks = lm.map((p) => [round4(p.x), round4(p.y), round4(p.z)]);
        const matrix = faceResult.facialTransformationMatrixes?.[0];
        if (matrix) headPose = headPoseFromMatrix(matrix.data);
        const result = emotionClassifier.classify(faceFull);
        emotion = result.emotion;
        emotionConfidence = result.confidence;
      }

      const handLandmarks: number[][] = [];
      let gesture = "none";
      let pointingVector: number[] | null = null;

      if (handResult.landmarks.length > 0) {
        for (const hand of handResult.landmarks) {
          for (const p of hand) {
            handLandmarks.push([round4(p.x), round4(p.y), round4(p.z)]);
          }
        }
        const firstHand = handResult.landmarks[0].map((p) => [p.x, p.y, p.z]);
        const g = gestureClassifier.classify(firstHand);
        gesture = gestureName(g.gestureType);
        if (g.pointingVector) pointingVector = g.pointingVector;
      }

      const frame: PerceptionFrame = {
        face_landmarks: faceLandmarks,
        emotion,
        emotion_confidence: emotionConfidence,
        head_pose: headPose,
        hand_landmarks: handLandmarks,
        gesture_name: gesture,
        pointing_vector: pointingVector,
        timestamp: Date.now() / 1000,
      };
      useAriaStore.getState().setVisionFrame(frame);

      // Face-exit interrupt: abort an in-flight cognition request locally when
      // the user leaves the frame (mirrors the server FaceExitDetector path).
      if (faceExit.update(faceDetected, now / 1000) && abortCognitionRef.current) {
        window.dispatchEvent(new CustomEvent("aria:interrupt"));
      }
    }

    async function start(): Promise<void> {
      try {
        setLoading(true);
        if (!navigator.mediaDevices?.getUserMedia) {
          throw new Error("Camera not supported in this browser");
        }

        const fileset = await FilesetResolver.forVisionTasks(WASM_PATH);
        faceLandmarker = await FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: FACE_MODEL_PATH },
          runningMode: "VIDEO",
          numFaces: 1,
          outputFacialTransformationMatrixes: true,
        });
        handLandmarker = await HandLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: HAND_MODEL_PATH },
          runningMode: "VIDEO",
          numHands: 2,
        });
        if (cancelled) {
          dispose();
          return;
        }

        stream = await navigator.mediaDevices.getUserMedia({ video: true });
        if (cancelled) {
          dispose();
          return;
        }

        video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        await video.play().catch(() => {
          // jsdom / autoplay-restricted contexts: detection loop still gates on
          // readyState, so a failed play() just delays the first frame.
        });
        if (cancelled) {
          dispose();
          return;
        }

        visionCaptureActiveRef.current = true;
        setActive(true);
        setLoading(false);
        setError(null);
        rafId = requestAnimationFrame(processFrame);
      } catch (err) {
        // Whatever was built before the failure must not outlive it.
        dispose();
        if (cancelled) return;
        setError(mapErrorMessage(err));
        setActive(false);
        setLoading(false);
        visionCaptureActiveRef.current = false;
      }
    }

    void start();

    return () => {
      cancelled = true;
      dispose();
      useAriaStore.getState().clearVisionFrame();
      visionCaptureActiveRef.current = false;
      setActive(false);
      setLoading(false);
    };
  }, [enabled]);

  return { active, loading, error };
}

# ARIA System Architecture

## Overview

ARIA is a three-language real-time system. Go manages concurrency and
WebSocket connections. Python handles all ML inference. TypeScript renders
the UI. Each layer is independently replaceable.

## System diagram

```
  Browser (Next.js)
       |
       | WebSocket ws://localhost:8080/ws
       | HTTP POST /api/cognition
       | HTTP POST /api/tts
       |
  Go Server (port 8080)
       |
       |-- Spawns --> Python Vision Worker
       |                  |
       |                  | MediaPipe Tasks (FaceMesh, Hands)
       |                  | Emotion classifier (landmark geometry)
       |                  | Head pose (solvePnP)
       |                  | Outputs JSON to stdout @ 15fps
       |
       |-- Spawns --> Python Audio Worker
                          |
                          | sounddevice (microphone capture)
                          | webrtcvad (voice activity detection)
                          | faster-whisper (speech-to-text)
                          | Outputs JSON to stdout on utterance end
```

## Data flow

Vision state (15fps):
```
  Webcam frame
  -> MediaPipe FaceMesh (478 landmarks)
  -> Emotion classifier (7 classes, 5-frame smoothing)
  -> Head pose estimation (solvePnP, pitch/yaw/roll)
  -> JSON stdout line
  -> Go reads stdout, broadcasts to all WebSocket clients
  -> Browser receives, updates landmark overlay and emotion display
```

Audio state (on utterance):
```
  Microphone audio (16kHz)
  -> webrtcvad (30ms chunks, utterance boundary detection)
  -> faster-whisper (base model, int8 quantization)
  -> JSON stdout line
  -> Go reads stdout, broadcasts transcript to WebSocket clients
  -> Browser receives transcript, auto-sends to /api/cognition
  -> Claude responds, browser calls /api/tts
  -> ElevenLabs streams audio, browser plays it
```

## Module responsibilities

### Go server (backend/cmd/, backend/internal/)
- Subprocess lifecycle management for Python workers
- WebSocket hub with concurrent client management
- POST /api/cognition — calls Anthropic Claude API
- POST /api/tts — streams ElevenLabs TTS audio
- GET /health — health check endpoint
- Graceful shutdown with 10-second drain

### Python vision worker (backend/app/pipeline/vision_worker.py)
- MediaPipe Tasks FaceLandmarker and HandLandmarker
- Head pose estimation via OpenCV solvePnP
- Landmark geometry emotion classifier (7 classes)
- Outputs one JSON frame per 66ms (15fps cap)
- Headless subprocess mode, --preview flag for development

### Python audio worker (backend/app/pipeline/audio_worker.py)
- sounddevice microphone capture at 16kHz
- webrtcvad voice activity detection (aggressiveness=2)
- faster-whisper base model transcription
- Outputs one JSON line per completed utterance
- --synthetic flag for CI environments without microphone

### Next.js frontend (frontend/src/)
- WebSocket client with exponential backoff reconnection
- Live landmark overlay on webcam feed via canvas
- Zustand store for all vision, audio, and conversation state
- useCognition hook for Claude API calls
- useTTS hook for audio playback
- VoiceIndicator component for recording/speaking states
- Avatar3D placeholder (full implementation in v0.7.0)

## JSON schemas

Vision frame (stdout from vision worker, broadcast over WebSocket):
```json
{
  "face_landmarks": [[x, y, z], ...],  // 478 points, normalized 0-1
  "emotion": "neutral",                // 7 classes
  "emotion_confidence": 0.73,          // 0.0 to 1.0
  "head_pose": {
    "pitch": -5.2,
    "yaw": 3.1,
    "roll": 0.8
  },
  "hand_landmarks": [[x, y, z], ...],  // 21 points per hand
  "timestamp": 1710000000.123
}
```

Audio transcript (stdout from audio worker, broadcast over WebSocket):
```json
{
  "type": "transcript",
  "payload": {
    "transcript": "what the user said",
    "is_final": true,
    "confidence": 0.94,
    "duration_ms": 1240,
    "timestamp": 1710000000.123
  }
}
```

Cognition request (POST /api/cognition):
```json
{
  "message": "user text",
  "vision_state": {
    "emotion": "happy",
    "head_pose": {"pitch": -5.2, "yaw": 3.1, "roll": 0.8},
    "face_detected": true,
    "hands_detected": false
  },
  "conversation_history": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

Cognition response:
```json
{
  "response": "ARIA response text",
  "emotion_suggestion": "neutral",
  "processing_ms": 342
}
```

## Environment configuration

All configuration via environment variables loaded from backend/.env.
See backend/.env.example for the full list.
Key variables: ANTHROPIC_API_KEY, PYTHON_BIN, AUDIO_ENABLED, WHISPER_MODEL.

## Planned changes

v0.5.0: Structured response object (spoken_text, avatar_emotion, intent)
v0.6.0: ChromaDB layered memory (profile, episodic, conversation)
v0.7.0: VRM avatar with three-vrm, lip sync, emotion blendshapes
v1.0.0: Gesture recognition, wake word detection

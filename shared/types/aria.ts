export interface VisionState {
  face_landmarks: number[][];
  emotion: string;
  head_pose: Record<string, number>;
}

export interface GestureState {
  gesture_name: string;
  confidence: number;
  hand_landmarks: number[][];
}

export interface AudioState {
  transcript: string;
  is_speaking: boolean;
}

export interface ARIAState {
  vision: VisionState;
  gesture: GestureState;
  audio: AudioState;
  timestamp: string;
}

export interface WebSocketMessage {
  type: string;
  payload: Record<string, unknown>;
}

export type AvatarEmotion =
  | "neutral"
  | "happy"
  | "sad"
  | "angry"
  | "surprised"
  | "fearful"
  | "disgusted";

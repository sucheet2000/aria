import { create } from "zustand";

export interface VisionFrame {
  face_landmarks: number[][];
  emotion: string;
  head_pose: { pitch: number; yaw: number; roll: number };
  hand_landmarks: number[][];
  timestamp: number;
}

export interface ARIAStore {
  // Connection
  wsConnected: boolean;
  wsError: string | null;

  // Vision data (raw from server)
  faceLandmarks: number[][];
  headPose: { pitch: number; yaw: number; roll: number };
  handLandmarks: number[][];
  emotion: string;
  lastFrameTimestamp: number;

  // Avatar state (derived/controlled)
  avatarEmotion: string;
  isSpeaking: boolean;
  isListening: boolean;

  // Conversation
  transcript: string;
  conversationHistory: Array<{ role: "user" | "assistant"; content: string }>;

  // Actions
  setWsConnected: (v: boolean) => void;
  setWsError: (v: string | null) => void;
  setVisionFrame: (frame: VisionFrame) => void;
  setAvatarEmotion: (v: string) => void;
  setIsSpeaking: (v: boolean) => void;
  setIsListening: (v: boolean) => void;
  setTranscript: (v: string) => void;
  addMessage: (role: "user" | "assistant", content: string) => void;
}

export const useAriaStore = create<ARIAStore>((set) => ({
  wsConnected: false,
  wsError: null,

  faceLandmarks: [],
  headPose: { pitch: 0, yaw: 0, roll: 0 },
  handLandmarks: [],
  emotion: "neutral",
  lastFrameTimestamp: 0,

  avatarEmotion: "neutral",
  isSpeaking: false,
  isListening: false,

  transcript: "",
  conversationHistory: [],

  setWsConnected: (v) => set({ wsConnected: v }),
  setWsError: (v) => set({ wsError: v }),
  setVisionFrame: (frame) =>
    set({
      faceLandmarks: frame.face_landmarks,
      headPose: frame.head_pose,
      handLandmarks: frame.hand_landmarks,
      emotion: frame.emotion,
      avatarEmotion: frame.emotion,
      lastFrameTimestamp: frame.timestamp,
    }),
  setAvatarEmotion: (v) => set({ avatarEmotion: v }),
  setIsSpeaking: (v) => set({ isSpeaking: v }),
  setIsListening: (v) => set({ isListening: v }),
  setTranscript: (v) => set({ transcript: v }),
  addMessage: (role, content) =>
    set((state) => ({
      conversationHistory: [...state.conversationHistory, { role, content }],
    })),
}));

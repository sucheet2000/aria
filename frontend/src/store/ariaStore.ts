import { create } from "zustand";

interface VisionState {
  face_landmarks: number[][];
  emotion: string;
  head_pose: Record<string, number>;
}

interface GestureState {
  gesture_name: string;
  confidence: number;
  hand_landmarks: number[][];
}

interface AriaStore {
  avatarEmotion: string;
  isListening: boolean;
  isSpeaking: boolean;
  transcript: string;
  visionState: VisionState | null;
  gestureState: GestureState | null;
  wsConnected: boolean;

  setAvatarEmotion: (emotion: string) => void;
  setIsListening: (listening: boolean) => void;
  setIsSpeaking: (speaking: boolean) => void;
  setTranscript: (transcript: string) => void;
  setVisionState: (state: VisionState | null) => void;
  setGestureState: (state: GestureState | null) => void;
  setWsConnected: (connected: boolean) => void;
}

export const useAriaStore = create<AriaStore>((set) => ({
  avatarEmotion: "neutral",
  isListening: false,
  isSpeaking: false,
  transcript: "",
  visionState: null,
  gestureState: null,
  wsConnected: false,

  setAvatarEmotion: (emotion) => set({ avatarEmotion: emotion }),
  setIsListening: (listening) => set({ isListening: listening }),
  setIsSpeaking: (speaking) => set({ isSpeaking: speaking }),
  setTranscript: (transcript) => set({ transcript }),
  setVisionState: (state) => set({ visionState: state }),
  setGestureState: (state) => set({ gestureState: state }),
  setWsConnected: (connected) => set({ wsConnected: connected }),
}));

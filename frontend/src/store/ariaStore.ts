import { create } from "zustand";

export interface VisionFrame {
  face_landmarks: number[][];
  emotion: string;
  emotion_confidence?: number;
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
  emotionConfidence: number;
  lastFrameTimestamp: number;

  // Avatar state (derived/controlled)
  avatarEmotion: string;
  isSpeaking: boolean;
  isListening: boolean;

  // Voice input state
  isRecording: boolean;
  voiceTranscript: string;
  voiceConfidence: number;

  // Audio output state
  audioQueue: string[];

  // API state
  processingMs: number;

  // Conversation
  transcript: string;
  conversationHistory: Array<{ role: "user" | "assistant"; content: string }>;

  // Memory
  profileFacts: string[];
  memoryLastUpdated: number;

  // Actions
  setWsConnected: (v: boolean) => void;
  setWsError: (v: string | null) => void;
  setVisionFrame: (frame: VisionFrame) => void;
  setAvatarEmotion: (v: string) => void;
  setIsSpeaking: (v: boolean) => void;
  setIsListening: (v: boolean) => void;
  setIsRecording: (v: boolean) => void;
  setVoiceTranscript: (v: string) => void;
  setVoiceConfidence: (v: number) => void;
  enqueueAudio: (text: string) => void;
  dequeueAudio: () => string | undefined;
  setTranscript: (v: string) => void;
  addMessage: (role: "user" | "assistant", content: string) => void;
  setEmotionConfidence: (v: number) => void;
  setProcessingMs: (v: number) => void;
  setProfileFacts: (facts: string[]) => void;
  setMemoryLastUpdated: (ts: number) => void;
}

export const useAriaStore = create<ARIAStore>((set, get) => ({
  wsConnected: false,
  wsError: null,

  faceLandmarks: [],
  headPose: { pitch: 0, yaw: 0, roll: 0 },
  handLandmarks: [],
  emotion: "neutral",
  emotionConfidence: 0,
  lastFrameTimestamp: 0,

  avatarEmotion: "neutral",
  isSpeaking: false,
  isListening: false,

  isRecording: false,
  voiceTranscript: "",
  voiceConfidence: 0,

  audioQueue: [],

  processingMs: 0,

  transcript: "",
  conversationHistory: [],

  profileFacts: [],
  memoryLastUpdated: 0,

  setWsConnected: (v) => set({ wsConnected: v }),
  setWsError: (v) => set({ wsError: v }),
  setVisionFrame: (frame) =>
    set({
      faceLandmarks: frame.face_landmarks,
      headPose: frame.head_pose,
      handLandmarks: frame.hand_landmarks,
      emotion: frame.emotion,
      emotionConfidence: frame.emotion_confidence ?? 0,
      avatarEmotion: frame.emotion,
      lastFrameTimestamp: frame.timestamp,
    }),
  setAvatarEmotion: (v) => set({ avatarEmotion: v }),
  setIsSpeaking: (v) => set({ isSpeaking: v }),
  setIsListening: (v) => set({ isListening: v }),
  setIsRecording: (v) => set({ isRecording: v }),
  setVoiceTranscript: (v) => set({ voiceTranscript: v }),
  setVoiceConfidence: (v) => set({ voiceConfidence: v }),
  enqueueAudio: (text) =>
    set((state) => ({ audioQueue: [...state.audioQueue, text] })),
  dequeueAudio: () => {
    const queue = get().audioQueue;
    if (queue.length === 0) return undefined;
    const [first, ...rest] = queue;
    set({ audioQueue: rest });
    return first;
  },
  setTranscript: (v) => set({ transcript: v }),
  addMessage: (role, content) =>
    set((state) => ({
      conversationHistory: [...state.conversationHistory, { role, content }],
    })),
  setEmotionConfidence: (v) => set({ emotionConfidence: v }),
  setProcessingMs: (v) => set({ processingMs: v }),
  setProfileFacts: (facts) => set({ profileFacts: facts }),
  setMemoryLastUpdated: (ts) => set({ memoryLastUpdated: ts }),
}));

import { create } from "zustand";

export interface WorldModelTriple {
  subject: string;
  predicate: string;
  object: string;
}

export interface WorldModelUpdate {
  triple: WorldModelTriple;
  confidence: number;
  source: string;
  timestamp: number;
}

export interface PerceptionFrame {
  face_landmarks: number[][];
  emotion: string;
  emotion_confidence?: number;
  head_pose: { pitch: number; yaw: number; roll: number };
  hand_landmarks: number[][];
  timestamp: number;
  gesture_name?: string;
  two_hand_gesture?: string;
  pointing_vector?: number[] | null;
}

export interface ARIAStore {
  // Connection
  wsConnected: boolean;
  wsError: string | null;

  // Perception INPUT (browser-derived, written by setVisionFrame /
  // clearVisionFrame; setEmotionConfidence is a legacy setter with no
  // callers): the user's estimated facial affect and its heuristic
  // confidence. Mirrors visionState.emotion / visionState.emotion_confidence.
  faceLandmarks: number[][];
  headPose: { pitch: number; yaw: number; roll: number };
  handLandmarks: number[][];
  emotion: string;
  emotionConfidence: number;
  lastFrameTimestamp: number;

  // Cognition OUTPUT (R3): ARIA's own response expression, owned by the
  // cognition response (setAvatarEmotion). Perception never writes it; an
  // empathetic mirror of the user's face is a cognition decision, not a
  // side effect of the camera loop.
  avatarEmotion: string;
  isSpeaking: boolean;
  isListening: boolean;
  isThinking: boolean;
  symbolicInference: string;

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
  // `localOnly` marks a message the client generated itself — an error notice,
  // not something ARIA said. It is shown to the user but never replayed to the
  // model, which must not read its own transcript as containing words it never
  // produced.
  conversationHistory: Array<{
    role: "user" | "assistant";
    content: string;
    localOnly?: boolean;
  }>;

  // Memory
  profileFacts: string[];
  memoryLastUpdated: number;

  // World model
  worldModelUpdates: WorldModelUpdate[];

  // Session
  sessionId: string;

  // Latest vision frame (includes gesture fields)
  visionState: PerceptionFrame | null;

  // Actions
  setWsConnected: (v: boolean) => void;
  setWsError: (v: string | null) => void;
  setSessionId: (id: string) => void;
  setVisionFrame: (frame: PerceptionFrame) => void;
  clearVisionFrame: () => void;
  setAvatarEmotion: (v: string) => void;
  setIsSpeaking: (v: boolean) => void;
  setIsListening: (v: boolean) => void;
  setIsThinking: (v: boolean) => void;
  setSymbolicInference: (v: string) => void;
  setIsRecording: (v: boolean) => void;
  setVoiceTranscript: (v: string) => void;
  setVoiceConfidence: (v: number) => void;
  enqueueAudio: (text: string) => void;
  dequeueAudio: () => string | undefined;
  setTranscript: (v: string) => void;
  addMessage: (
    role: "user" | "assistant",
    content: string,
    options?: { localOnly?: boolean },
  ) => void;
  clearConversation: () => void;
  setEmotionConfidence: (v: number) => void;
  setProcessingMs: (v: number) => void;
  setProfileFacts: (facts: string[]) => void;
  setMemoryLastUpdated: (ts: number) => void;
  addWorldModelUpdate: (update: WorldModelUpdate) => void;
  clearWorldModel: () => void;
}

export const useAriaStore = create<ARIAStore>((set, get) => ({
  wsConnected: false,
  wsError: null,
  sessionId: crypto.randomUUID(),

  faceLandmarks: [],
  headPose: { pitch: 0, yaw: 0, roll: 0 },
  handLandmarks: [],
  emotion: "neutral",
  emotionConfidence: 0,
  lastFrameTimestamp: 0,

  avatarEmotion: "neutral",
  isSpeaking: false,
  isListening: false,
  isThinking: false,
  symbolicInference: "",

  isRecording: false,
  voiceTranscript: "",
  voiceConfidence: 0,

  audioQueue: [],

  processingMs: 0,

  transcript: "",
  conversationHistory: [],

  profileFacts: [],
  memoryLastUpdated: 0,

  worldModelUpdates: [],

  visionState: null,

  setWsConnected: (v) => set({ wsConnected: v }),
  setWsError: (v) => set({ wsError: v }),
  setSessionId: (id) => set({ sessionId: id }),
  setVisionFrame: (frame: PerceptionFrame) =>
    set({
      faceLandmarks: frame.face_landmarks,
      headPose: frame.head_pose,
      handLandmarks: frame.hand_landmarks,
      emotion: frame.emotion,
      emotionConfidence: frame.emotion_confidence ?? 0,
      lastFrameTimestamp: frame.timestamp,
      visionState: frame,
    }),
  // Leaves avatarEmotion untouched (R3): the avatar is driven by the
  // cognition response, not by camera teardown.
  clearVisionFrame: () =>
    set({
      faceLandmarks: [],
      headPose: { pitch: 0, yaw: 0, roll: 0 },
      handLandmarks: [],
      emotion: "neutral",
      emotionConfidence: 0,
      lastFrameTimestamp: 0,
      visionState: null,
    }),
  setAvatarEmotion: (v) => set({ avatarEmotion: v }),
  setIsSpeaking: (v) => set({ isSpeaking: v }),
  setIsListening: (v) => set({ isListening: v }),
  setIsThinking: (v) => set({ isThinking: v }),
  setSymbolicInference: (v) => set({ symbolicInference: v }),
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
  clearConversation: () => set({ conversationHistory: [] }),
  addMessage: (role, content, options) =>
    set((state) => ({
      conversationHistory: [
        ...state.conversationHistory,
        options?.localOnly ? { role, content, localOnly: true } : { role, content },
      ],
    })),
  setEmotionConfidence: (v) => set({ emotionConfidence: v }),
  setProcessingMs: (v) => set({ processingMs: v }),
  setProfileFacts: (facts) => set({ profileFacts: facts }),
  setMemoryLastUpdated: (ts) => set({ memoryLastUpdated: ts }),
  addWorldModelUpdate: (update) =>
    set((state) => ({
      worldModelUpdates: [...state.worldModelUpdates, update],
    })),
  clearWorldModel: () => set({ worldModelUpdates: [] }),
}));

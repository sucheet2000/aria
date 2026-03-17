"use client";

import { useAriaStore } from "@/store/ariaStore";

export default function ChatPanel() {
  const { transcript, isListening, isSpeaking } = useAriaStore();

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-aria-accent/20 bg-aria-surface p-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-aria-glow">
          Chat
        </h2>
        {isListening && (
          <span className="h-2 w-2 animate-pulse rounded-full bg-green-400" />
        )}
        {isSpeaking && (
          <span className="h-2 w-2 animate-pulse rounded-full bg-aria-accent" />
        )}
      </div>

      <div className="min-h-[80px] rounded-lg bg-black/30 p-3 text-sm text-slate-300">
        {transcript || <span className="text-slate-600">Listening…</span>}
      </div>

      <div className="flex gap-2">
        <button
          className="flex-1 rounded-lg bg-aria-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-aria-glow"
          type="button"
        >
          {isListening ? "Stop" : "Listen"}
        </button>
      </div>
    </div>
  );
}

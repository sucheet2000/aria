"use client";

import Avatar3D from "@/components/Avatar3D";
import CameraFeed from "@/components/CameraFeed";
import ChatPanel from "@/components/ChatPanel";
import { useWebSocket } from "@/hooks/useWebSocket";

export default function Home() {
  useWebSocket();

  return (
    <main className="flex h-screen w-screen overflow-hidden bg-aria-dark">
      <div className="w-80 flex-shrink-0 flex flex-col gap-4 p-4 overflow-hidden">
        <h1 className="text-3xl font-bold tracking-widest text-aria-accent">ARIA</h1>
        <CameraFeed />
        <ChatPanel />
      </div>
      <div className="flex-1 p-4">
        <Avatar3D />
      </div>
    </main>
  );
}

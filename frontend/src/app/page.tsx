"use client";

import Avatar3D from "@/components/Avatar3D";
import CameraFeed from "@/components/CameraFeed";
import ChatPanel from "@/components/ChatPanel";

export default function Home() {
  return (
    <main className="flex h-screen w-screen overflow-hidden bg-aria-dark">
      {/* Left panel */}
      <div className="flex w-1/2 flex-col gap-4 p-4">
        <CameraFeed />
        <ChatPanel />
      </div>

      {/* Right panel */}
      <div className="flex w-1/2 items-center justify-center p-4">
        <Avatar3D />
      </div>
    </main>
  );
}

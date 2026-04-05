"use client";

import { useEffect, useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stars } from "@react-three/drei";
import { useWorldModel } from "./useWorldModel";
import { AnchorMarker } from "./AnchorMarker";
import { useSpatialSync, broadcastAnchorAdded } from "./useSpatialSync";
import type { SpatialAnchor } from "./useWorldModel";

interface AnchorRegisteredPayload {
  id: string;
  label: string;
  x?: number;
  y?: number;
  z?: number;
}

export function SpatialCanvas() {
  const anchors = useWorldModel((s) => s.anchors);
  const addAnchor = useWorldModel((s) => s.addAnchor);

  useSpatialSync();

  useEffect(() => {
    function handleAnchorRegistered(e: Event) {
      const payload = (e as CustomEvent<AnchorRegisteredPayload>).detail;
      if (!payload?.id || payload.label === undefined) return;
      const anchor: SpatialAnchor = {
        id: payload.id,
        label: payload.label,
        x: payload.x ?? 0,
        y: payload.y ?? 0,
        z: payload.z ?? 0,
      };
      addAnchor(anchor);
      broadcastAnchorAdded(anchor);
    }

    window.addEventListener("aria:anchor_registered", handleAnchorRegistered);
    return () => {
      window.removeEventListener("aria:anchor_registered", handleAnchorRegistered);
    };
  }, [addAnchor]);

  const cameraConfig = useMemo(
    () => ({ position: [0, 0, 5] as [number, number, number], fov: 60 }),
    []
  );

  return (
    <Canvas camera={cameraConfig}>
      <ambientLight intensity={0.3} />
      <pointLight position={[10, 10, 10]} intensity={0.8} />
      <Stars radius={100} depth={50} count={3000} factor={4} saturation={0} fade />
      {Array.from(anchors.values()).map((anchor) => (
        <AnchorMarker key={anchor.id} anchor={anchor} />
      ))}
      <OrbitControls enablePan={false} enableZoom={false} />
    </Canvas>
  );
}

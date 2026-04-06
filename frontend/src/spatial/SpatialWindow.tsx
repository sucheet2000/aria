"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls, Stars } from "@react-three/drei";
import { useMemo } from "react";
import { useWorldModel } from "./useWorldModel";
import { AnchorMarker } from "./AnchorMarker";
import { useSpatialSync } from "./useSpatialSync";

export function SpatialWindow() {
  const anchors = useWorldModel((s) => s.anchors);
  const cameraConfig = useMemo(
    () => ({ position: [0, 0, 5] as [number, number, number], fov: 60 }),
    []
  );

  useSpatialSync();

  return (
    <div style={{ width: "100vw", height: "100dvh", background: "#000" }}>
      <Canvas camera={cameraConfig}>
        <ambientLight intensity={0.3} />
        <pointLight position={[10, 10, 10]} intensity={0.8} />
        <Stars radius={100} depth={50} count={3000} factor={4} saturation={0} fade />
        {Array.from(anchors.values()).map((anchor) => (
          <AnchorMarker key={anchor.id} anchor={anchor} />
        ))}
        <OrbitControls enablePan={false} enableZoom={false} />
      </Canvas>
    </div>
  );
}

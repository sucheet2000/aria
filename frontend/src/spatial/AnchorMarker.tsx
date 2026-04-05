"use client";

import { useRef, useState } from "react";
import { ThreeEvent } from "@react-three/fiber";
import { Text } from "@react-three/drei";
import * as THREE from "three";
import type { SpatialAnchor } from "./useWorldModel";

const LABEL_COLOR_MAP: Array<[string, string]> = [
  ["person", "#00d4ff"],
  ["object", "#ff6b35"],
  ["place", "#7cfc00"],
  ["event", "#ff00ff"],
  ["item", "#ffcc00"],
];

function getLabelColor(label: string): string {
  const lower = label.toLowerCase();
  for (const [key, color] of LABEL_COLOR_MAP) {
    if (lower.includes(key)) return color;
  }
  return "#88aaff";
}

interface AnchorMarkerProps {
  anchor: SpatialAnchor;
}

export function AnchorMarker({ anchor }: AnchorMarkerProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const color = getLabelColor(anchor.label);

  return (
    <group position={[anchor.x, anchor.y, anchor.z]}>
      <mesh
        ref={meshRef}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[hovered ? 0.12 : 0.1, 16, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={hovered ? 1.5 : 0.8}
          transparent
          opacity={0.9}
        />
      </mesh>
      {hovered && (
        <Text
          position={[0, 0.22, 0]}
          fontSize={0.08}
          color={color}
          anchorX="center"
          anchorY="bottom"
          outlineWidth={0.004}
          outlineColor="#000000"
        >
          {anchor.label}
        </Text>
      )}
    </group>
  );
}

"use client";

import { useRef, useState } from "react";
import { useFrame, ThreeEvent } from "@react-three/fiber";
import { Text } from "@react-three/drei";
import * as THREE from "three";
import type { SpatialAnchor } from "./useWorldModel";
import { useWorldModel } from "./useWorldModel";

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
  const groupRef = useRef<THREE.Group>(null);
  const [hovered, setHovered] = useState(false);
  const color = getLabelColor(anchor.label);
  const setAnchorVelocity = useWorldModel((s) => s.setAnchorVelocity);

  useFrame(() => {
    const v = anchor.velocity;
    if (!v) return;
    const mag = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
    if (mag < 0.001) return;

    const next: [number, number, number] = [v[0] * 0.95, v[1] * 0.95, v[2] * 0.95];
    const newX = anchor.x + v[0];
    const newY = anchor.y + v[1];
    const newZ = anchor.z + v[2];

    if (groupRef.current) {
      groupRef.current.position.set(newX, newY, newZ);
    }

    const nextMag = Math.sqrt(next[0] * next[0] + next[1] * next[1] + next[2] * next[2]);
    if (nextMag < 0.001) {
      setAnchorVelocity(anchor.id, [0, 0, 0]);
    } else {
      useWorldModel.setState((state) => {
        const existing = state.anchors.get(anchor.id);
        if (!existing) return {};
        const updated = { ...existing, x: newX, y: newY, z: newZ, velocity: next };
        const next_map = new Map(state.anchors);
        next_map.set(anchor.id, updated);
        return { anchors: next_map };
      });
    }
  });

  return (
    <group ref={groupRef} position={[anchor.x, anchor.y, anchor.z]}>
      <mesh
        ref={meshRef}
        scale={hovered ? 1.2 : 1}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          e.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        <sphereGeometry args={[0.1, 16, 16]} />
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

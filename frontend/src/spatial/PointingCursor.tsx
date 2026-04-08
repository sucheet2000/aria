"use client";

import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

interface PointingCursorProps {
  vector: [number, number, number];
}

export function PointingCursor({ vector }: PointingCursorProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const position: [number, number, number] = [
    vector[0] * 2,
    vector[1] * 2,
    vector[2] * 2,
  ];

  useFrame(({ clock }) => {
    if (meshRef.current) {
      const s = 1 + 0.3 * Math.sin(clock.elapsedTime * 8);
      meshRef.current.scale.setScalar(s);
    }
  });

  return (
    <mesh ref={meshRef} position={position}>
      <sphereGeometry args={[0.06, 12, 12]} />
      <meshStandardMaterial
        color="#ffffff"
        emissive="#ffffff"
        emissiveIntensity={2}
        transparent
        opacity={0.7}
      />
    </mesh>
  );
}

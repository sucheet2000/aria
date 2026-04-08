"use client";

import { useEffect, useRef, useState } from "react";
import { useFrame, ThreeEvent } from "@react-three/fiber";
import { Text } from "@react-three/drei";
import * as THREE from "three";
import type { SpatialAnchor } from "./useWorldModel";
import { useWorldModel } from "./useWorldModel";
import { deleteAnchor } from "./deleteAnchorFn";

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
  const activeGesture = useWorldModel((s) => s.activeGesture);

  // Local refs track animated position and velocity — no Zustand writes in the
  // render loop. Store is only written once when velocity decays to zero.
  const positionRef = useRef<[number, number, number]>([anchor.x, anchor.y, anchor.z]);
  const velocityRef = useRef<[number, number, number] | null>(anchor.velocity ?? null);

  // Sync refs when a new throw arrives from the store.
  useEffect(() => {
    if (anchor.velocity) {
      velocityRef.current = anchor.velocity;
      positionRef.current = [anchor.x, anchor.y, anchor.z];
    }
  }, [anchor.velocity, anchor.x, anchor.y, anchor.z]);

  useFrame(({ clock }) => {
    const v = velocityRef.current;
    if (v) {
      const mag = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
      if (mag < 0.001) {
        velocityRef.current = null;
        setAnchorVelocity(anchor.id, [0, 0, 0]); // store write: once to clear
      } else {
        const next: [number, number, number] = [v[0] * 0.95, v[1] * 0.95, v[2] * 0.95];
        positionRef.current = [
          positionRef.current[0] + v[0],
          positionRef.current[1] + v[1],
          positionRef.current[2] + v[2],
        ];
        velocityRef.current = next;
        if (groupRef.current) {
          groupRef.current.position.set(
            positionRef.current[0],
            positionRef.current[1],
            positionRef.current[2],
          );
        }
      }
    }

    // BOND/EXPAND pulse: animate scale on the mesh
    if (meshRef.current && (activeGesture === "BOND" || activeGesture === "EXPAND")) {
      const pulse = 1 + 0.25 * Math.abs(Math.sin(clock.elapsedTime * 12));
      meshRef.current.scale.setScalar(pulse);
    }
  });

  const emissiveIntensity = (() => {
    if (activeGesture === "BOND" || activeGesture === "EXPAND") return 3.0;
    if (hovered) return 1.5;
    return 0.8;
  })();

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
          emissiveIntensity={emissiveIntensity}
          transparent
          opacity={0.9}
        />
      </mesh>
      {hovered && (
        <>
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
          {/* Delete button: small red sphere above the label */}
          <mesh
            position={[0, 0.38, 0]}
            onClick={(e: ThreeEvent<MouseEvent>) => {
              e.stopPropagation();
              deleteAnchor(anchor.id);
            }}
          >
            <sphereGeometry args={[0.04, 8, 8]} />
            <meshStandardMaterial color="#ff3333" emissive="#ff0000" emissiveIntensity={1.5} />
          </mesh>
        </>
      )}
    </group>
  );
}

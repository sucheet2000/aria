"use client";

import React, { Component, Suspense } from "react";
import { Canvas, useFrame, useLoader } from "@react-three/fiber";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  VRMLoaderPlugin,
  VRM,
  VRMExpressionPresetName,
  VRMHumanBoneName,
} from "@pixiv/three-vrm";
import * as THREE from "three";
import { useAriaStore } from "@/store/ariaStore";
import Avatar3D from "./Avatar3D";

// All expression presets we drive — reset these each frame before applying emotion
const DRIVEN_EXPRS: VRMExpressionPresetName[] = [
  VRMExpressionPresetName.Aa,
  VRMExpressionPresetName.Ih,
  VRMExpressionPresetName.Ou,
  VRMExpressionPresetName.Oh,
];

// Emotion → list of (expression, weight) pairs
const EMOTION_EXPRS: Record<string, Array<{ expr: VRMExpressionPresetName; weight: number }>> = {
  happy:    [{ expr: VRMExpressionPresetName.Aa, weight: 0.6 }],
  sad:      [{ expr: VRMExpressionPresetName.Ih, weight: 0.5 }],
  angry:    [{ expr: VRMExpressionPresetName.Ou, weight: 0.7 }],
  surprised:[{ expr: VRMExpressionPresetName.Oh, weight: 0.8 }],
  neutral:  [],
};

// ─── Inner Three.js component — suspends while loading ───────────────────────

function VRMScene() {
  const avatarEmotion = useAriaStore((s) => s.avatarEmotion);
  const headPose = useAriaStore((s) => s.headPose);

  const gltf = useLoader(
    GLTFLoader,
    "/model/avatar.vrm",
    (loader) => {
      loader.register((parser) => new VRMLoaderPlugin(parser));
    },
  ) as unknown as { scene: THREE.Group; userData: { vrm?: VRM } };

  const vrm = gltf.userData.vrm;

  useFrame((_state, delta) => {
    if (!vrm) return;

    // Idle breathing — subtle chest Y scale oscillation
    const chest = vrm.humanoid?.getNormalizedBoneNode(VRMHumanBoneName.Chest);
    if (chest) {
      chest.scale.y = 1 + 0.015 * Math.sin(_state.clock.elapsedTime * 1.2);
    }

    // Emotion blendshapes
    if (vrm.expressionManager) {
      for (const expr of DRIVEN_EXPRS) {
        vrm.expressionManager.setValue(expr, 0);
      }
      for (const { expr, weight } of EMOTION_EXPRS[avatarEmotion] ?? []) {
        vrm.expressionManager.setValue(expr, weight);
      }
      vrm.expressionManager.update();
    }

    // Head pose from vision state (degrees → radians); guard against null frame
    const head = vrm.humanoid?.getNormalizedBoneNode(VRMHumanBoneName.Head);
    if (head && headPose) {
      const DEG = Math.PI / 180;
      head.rotation.set(
        headPose.pitch * DEG,
        headPose.yaw * DEG,
        headPose.roll * DEG,
      );
    }

    vrm.update(delta);
  });

  if (!vrm) return null;

  return <primitive object={vrm.scene} />;
}

// ─── Error boundary — catches VRM load/parse failures ────────────────────────

interface BoundaryProps {
  fallback: React.ReactNode;
  children: React.ReactNode;
}

interface BoundaryState {
  hasError: boolean;
}

class VRMErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { hasError: false };

  static getDerivedStateFromError(): BoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}

// ─── Public component ─────────────────────────────────────────────────────────

export default function VRMAvatar() {
  return (
    <VRMErrorBoundary fallback={<Avatar3D />}>
      <Canvas camera={{ position: [0, 1.4, 2.5], fov: 35 }}>
        <ambientLight intensity={0.6} />
        <directionalLight position={[1, 2, 2]} intensity={1.2} />
        <Suspense fallback={null}>
          <VRMScene />
        </Suspense>
      </Canvas>
    </VRMErrorBoundary>
  );
}

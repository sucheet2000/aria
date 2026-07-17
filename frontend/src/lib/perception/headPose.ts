// Head pose (pitch/yaw/roll in degrees) from MediaPipe FaceLandmarker's
// facialTransformationMatrixes output. This replaces the Python solvePnP path in
// vision_worker.py: MediaPipe already solves the rigid head transform, so we
// only decompose its rotation into Tait-Bryan (XYZ) Euler angles.
//
// The matrix `data` is a 4x4 column-major array (THREE.Matrix4.fromArray
// convention), so rotation element R[row][col] = data[col * 4 + row].

export interface HeadPose {
  pitch: number;
  yaw: number;
  roll: number;
}

const ZERO: HeadPose = { pitch: 0, yaw: 0, roll: 0 };

function round2(v: number): number {
  // `|| 0` collapses negative zero (from atan2(-0, ...)) to 0.
  return Math.round(v * 100) / 100 || 0;
}

function toDeg(rad: number): number {
  return (rad * 180) / Math.PI;
}

export function headPoseFromMatrix(data: readonly number[] | Float32Array): HeadPose {
  if (!data || data.length < 16) return { ...ZERO };

  const r = (row: number, col: number): number => data[col * 4 + row];

  const r00 = r(0, 0);
  const r10 = r(1, 0);
  const r20 = r(2, 0);
  const r21 = r(2, 1);
  const r22 = r(2, 2);
  const r11 = r(1, 1);
  const r12 = r(1, 2);

  const sy = Math.sqrt(r00 * r00 + r10 * r10);

  let pitch: number;
  let yaw: number;
  let roll: number;

  if (sy > 1e-6) {
    pitch = Math.atan2(r21, r22);
    yaw = Math.atan2(-r20, sy);
    roll = Math.atan2(r10, r00);
  } else {
    // Gimbal lock: yaw near ±90°, roll is indeterminate -> fold into pitch.
    pitch = Math.atan2(-r12, r11);
    yaw = Math.atan2(-r20, sy);
    roll = 0;
  }

  return {
    pitch: round2(toDeg(pitch)),
    yaw: round2(toDeg(yaw)),
    roll: round2(toDeg(roll)),
  };
}

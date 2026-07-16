import { describe, it, expect } from "vitest";
import { headPoseFromMatrix } from "./headPose";

// MediaPipe's facialTransformationMatrixes[i].data is a 4x4 column-major matrix
// (THREE.Matrix4.fromArray convention). We build column-major test matrices and
// assert the extracted pitch/yaw/roll (degrees) match the applied rotation.

function columnMajor(r: number[][]): number[] {
  // r is a 3x3 row-major rotation; embed into a column-major 4x4 array.
  const m = new Array(16).fill(0);
  for (let row = 0; row < 3; row++) {
    for (let col = 0; col < 3; col++) {
      m[col * 4 + row] = r[row][col];
    }
  }
  m[15] = 1;
  return m;
}

const deg = (d: number) => (d * Math.PI) / 180;

describe("headPoseFromMatrix", () => {
  it("returns zero angles for the identity matrix", () => {
    const identity = columnMajor([
      [1, 0, 0],
      [0, 1, 0],
      [0, 0, 1],
    ]);
    const pose = headPoseFromMatrix(identity);
    expect(pose.pitch).toBe(0);
    expect(pose.yaw).toBe(0);
    expect(pose.roll).toBe(0);
  });

  it("extracts yaw from a rotation about the Y axis", () => {
    const t = deg(30);
    const ry = [
      [Math.cos(t), 0, Math.sin(t)],
      [0, 1, 0],
      [-Math.sin(t), 0, Math.cos(t)],
    ];
    const pose = headPoseFromMatrix(columnMajor(ry));
    expect(pose.yaw).toBeCloseTo(30, 1);
    expect(pose.pitch).toBeCloseTo(0, 1);
    expect(pose.roll).toBeCloseTo(0, 1);
  });

  it("extracts pitch from a rotation about the X axis", () => {
    const t = deg(20);
    const rx = [
      [1, 0, 0],
      [0, Math.cos(t), -Math.sin(t)],
      [0, Math.sin(t), Math.cos(t)],
    ];
    const pose = headPoseFromMatrix(columnMajor(rx));
    expect(pose.pitch).toBeCloseTo(20, 1);
    expect(pose.yaw).toBeCloseTo(0, 1);
    expect(pose.roll).toBeCloseTo(0, 1);
  });

  it("extracts roll from a rotation about the Z axis", () => {
    const t = deg(15);
    const rz = [
      [Math.cos(t), -Math.sin(t), 0],
      [Math.sin(t), Math.cos(t), 0],
      [0, 0, 1],
    ];
    const pose = headPoseFromMatrix(columnMajor(rz));
    expect(pose.roll).toBeCloseTo(15, 1);
    expect(pose.pitch).toBeCloseTo(0, 1);
    expect(pose.yaw).toBeCloseTo(0, 1);
  });

  it("returns zero angles when the matrix is malformed", () => {
    const pose = headPoseFromMatrix([1, 2, 3]);
    expect(pose).toEqual({ pitch: 0, yaw: 0, roll: 0 });
  });
});

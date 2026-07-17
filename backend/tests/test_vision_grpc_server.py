"""
Tests for the gRPC vision server wrapper.
Requires generated proto stubs — skips gracefully if grpc not installed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("grpc", reason="grpcio not installed")

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend" / "gen" / "python"))

from perception.v1 import perception_pb2  # noqa: E402

from app.pipeline.vision_grpc_server import PerceptionServicer  # noqa: E402


def test_push_frame_enqueues_frame() -> None:
    """push_frame should place the frame onto the internal queue."""
    servicer = PerceptionServicer()
    frame = perception_pb2.PerceptionFrame()
    servicer.push_frame(frame)
    got = servicer._frame_queue.get_nowait()
    assert got is frame


def test_push_frame_drops_when_queue_full() -> None:
    """push_frame must not block or raise when queue is at capacity (maxsize=10)."""
    servicer = PerceptionServicer()
    for _ in range(10):
        servicer.push_frame(perception_pb2.PerceptionFrame())
    # 11th push should be silently dropped
    servicer.push_frame(perception_pb2.PerceptionFrame())
    assert servicer._frame_queue.qsize() == 10


def test_push_frame_with_hand_data() -> None:
    """PerceptionFrame with HandData round-trips through the queue intact."""
    servicer = PerceptionServicer()
    frame = perception_pb2.PerceptionFrame(
        hands=[
            perception_pb2.HandData(
                landmarks=[perception_pb2.Point3D(x=0.1, y=0.2, z=0.3)]
            )
        ]
    )
    servicer.push_frame(frame)
    got = servicer._frame_queue.get_nowait()
    assert len(got.hands) == 1
    assert got.hands[0].landmarks[0].x == pytest.approx(0.1)

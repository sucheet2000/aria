"""
gRPC server wrapper for the vision worker.
Serves PerceptionFrame messages on port 50051.
"""
from __future__ import annotations

import queue
import sys
from concurrent import futures
from pathlib import Path

import grpc
import structlog

# Add generated stubs to path — works whether PYTHONPATH=backend (normal) or
# run directly from the backend/ directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gen" / "python"))
from perception.v1 import perception_pb2, perception_pb2_grpc  # noqa: E402

logger = structlog.get_logger()

GRPC_PORT = 50051


class PerceptionServicer(perception_pb2_grpc.PerceptionServiceServicer):
    """Implements the PerceptionService gRPC server."""

    def __init__(self) -> None:
        self._frame_queue: queue.Queue = queue.Queue(maxsize=10)

    def push_frame(self, frame: perception_pb2.PerceptionFrame) -> None:
        """Called by the vision worker to push a new frame. Non-blocking — drops when full."""
        try:
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    def StreamFrames(self, request, context):
        """Server-streaming RPC — yields PerceptionFrames to the Go client."""
        logger.info("vision gRPC client connected", session_id=request.session_id)
        try:
            while context.is_active():
                try:
                    frame = self._frame_queue.get(timeout=0.1)
                    yield frame
                except queue.Empty:
                    continue
        finally:
            logger.info("vision gRPC client disconnected")


def serve(servicer: PerceptionServicer) -> grpc.Server:
    """Start the gRPC server on GRPC_PORT. Returns the server instance."""
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=2),
        options=[
            ("grpc.max_send_message_length", 1024 * 1024),
            ("grpc.max_receive_message_length", 1024 * 1024),
        ],
    )
    perception_pb2_grpc.add_PerceptionServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"127.0.0.1:{GRPC_PORT}")
    server.start()
    logger.info("vision gRPC server started", port=GRPC_PORT)
    return server

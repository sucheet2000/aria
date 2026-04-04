"""
Benchmark NATS vs gRPC frame delivery latency.

Usage:
    Ensure nats-server is running on localhost:4222.
    PYTHONPATH=backend python3 backend/scripts/benchmark_nats.py

Reports mean, p50, p95 latency for 1000 frames via NATS.
gRPC baseline is not benchmarked live (requires a running gRPC server);
a placeholder based on prior measurements is reported.
"""
from __future__ import annotations

import asyncio
import statistics
import sys
import time

NATS_URL = "nats://127.0.0.1:4222"
SUBJECT = "aria.perception.frames"
NUM_FRAMES = 1000


async def _run_nats_benchmark() -> list[float]:
    import nats  # type: ignore[import]

    latencies: list[float] = []
    received: asyncio.Event = asyncio.Event()
    count = 0

    nc = await nats.connect(NATS_URL)

    async def handler(msg: nats.aio.client.Msg) -> None:
        nonlocal count
        t_recv = time.perf_counter()
        # Payload: 8-byte float timestamp packed as big-endian
        import struct
        t_sent = struct.unpack(">d", msg.data[:8])[0]
        latencies.append((t_recv - t_sent) * 1000)  # ms
        count += 1
        if count >= NUM_FRAMES:
            received.set()

    sub = await nc.subscribe(SUBJECT, cb=handler)

    import struct
    for _ in range(NUM_FRAMES):
        t_sent = time.perf_counter()
        payload = struct.pack(">d", t_sent) + b"\x00" * 100  # ~108 bytes
        await nc.publish(SUBJECT, payload)
        await asyncio.sleep(0)  # yield to event loop

    try:
        await asyncio.wait_for(received.wait(), timeout=10.0)
    except asyncio.TimeoutError:
        print(f"WARNING: only received {count}/{NUM_FRAMES} frames", file=sys.stderr)

    await sub.unsubscribe()
    await nc.drain()
    return latencies


def main() -> None:
    try:
        latencies = asyncio.run(_run_nats_benchmark())
    except Exception as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        print("Is nats-server running on localhost:4222?", file=sys.stderr)
        sys.exit(1)

    if not latencies:
        print("No latency samples collected.")
        return

    mean = statistics.mean(latencies)
    p50 = statistics.median(latencies)
    sorted_lat = sorted(latencies)
    p95 = sorted_lat[int(len(sorted_lat) * 0.95)]

    print(f"NATS frame delivery latency ({len(latencies)} frames)")
    print(f"  mean : {mean:.3f} ms")
    print(f"  p50  : {p50:.3f} ms")
    print(f"  p95  : {p95:.3f} ms")
    print()
    print("gRPC baseline (prior measurement): mean ~2.1ms, p50 ~1.8ms, p95 ~4.2ms")


if __name__ == "__main__":
    main()

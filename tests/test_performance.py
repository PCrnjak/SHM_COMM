"""
Performance benchmarks for shm_comm.

Run with: pytest tests/test_performance.py -v -s

These tests are not regular unit tests — they measure and *report*
performance numbers. They do not assert hard thresholds (hardware
varies) but they will fail if the library produces errors.
"""

import time
import statistics
import pytest

from shm_comm import Publisher, Subscriber, Pusher, Puller, force_unlink
from shm_comm.utils import pub_segment_name, push_segment_name

MSG_COUNTS = [1_000, 10_000]
PAYLOAD_SIZES = [64, 512, 4096 - 4]  # bytes (last is max for default slot)


def _make_payload(size: int) -> bytes:
    return b"x" * size


# ── Throughput: Publisher → Subscriber ───────────────────────────────────────

@pytest.mark.parametrize("n_msgs", MSG_COUNTS)
@pytest.mark.parametrize("payload_size", PAYLOAD_SIZES)
def test_pubsub_throughput(n_msgs, payload_size):
    ch = "perf_throughput"
    force_unlink(pub_segment_name(ch))

    payload = _make_payload(payload_size)
    sent = 0
    received = 0
    # Ring must hold all messages to avoid wrap-around conflicting with
    # the subscriber's private tail (SPSC empty-detection ambiguity).
    num_slots = n_msgs + 64

    with Publisher(ch, num_slots=num_slots, slot_size=4096) as pub:
        with Subscriber(ch) as sub:
            # --- send phase ---
            t0 = time.perf_counter()
            for _ in range(n_msgs):
                if pub.send_bytes(payload):
                    sent += 1
            t_send = time.perf_counter() - t0

            # --- recv phase ---
            t0 = time.perf_counter()
            while received < sent:
                raw = sub.recv_bytes(timeout=2.0)
                if raw is not None:
                    received += 1
            t_recv = time.perf_counter() - t0

    throughput = sent / t_send
    print(
        f"\n[throughput] payload={payload_size}B n={n_msgs}: "
        f"send={throughput/1e3:.1f}k msg/s  "
        f"recv={received/t_recv/1e3:.1f}k msg/s  "
        f"sent={sent} recv={received}"
    )
    assert received == sent


# ── Round-trip latency ────────────────────────────────────────────────────────

def test_pubsub_latency():
    """Measure one-way write→read latency via a simple loopback."""
    ch = "perf_latency"
    force_unlink(pub_segment_name(ch))

    N = 1000
    latencies = []

    with Publisher(ch, num_slots=256, slot_size=256) as pub:
        with Subscriber(ch) as sub:
            for _ in range(N):
                t0 = time.perf_counter()
                pub.send_bytes(b"ping")
                raw = sub.recv_bytes(timeout=1.0)
                latency_us = (time.perf_counter() - t0) * 1e6
                assert raw == b"ping"
                latencies.append(latency_us)

    p50 = statistics.median(latencies)
    p99 = sorted(latencies)[int(0.99 * N)]
    p_min = min(latencies)
    p_max = max(latencies)

    print(
        f"\n[latency] n={N}: "
        f"min={p_min:.1f}µs  p50={p50:.1f}µs  "
        f"p99={p99:.1f}µs  max={p_max:.1f}µs"
    )


# ── Serialization overhead ────────────────────────────────────────────────────

def test_serialization_overhead():
    """Compare pickle vs raw bytes throughput."""
    import pickle
    ch = "perf_serial"
    force_unlink(pub_segment_name(ch))
    N = 5000
    data = {"pos": [1.0, 2.0, 3.0], "vel": [0.1, 0.2, 0.3]}

    # pickle path
    t0 = time.perf_counter()
    with Publisher(ch, num_slots=N + 64) as pub:
        with Subscriber(ch, serialization="pickle") as sub:
            for _ in range(N):
                pub.send(data)
            received = 0
            while received < N:
                m = sub.recv(timeout=2.0)
                if m:
                    received += 1
    t_pickle = time.perf_counter() - t0

    # raw bytes path
    raw_payload = pickle.dumps(data)
    force_unlink(pub_segment_name(ch))
    t0 = time.perf_counter()
    with Publisher(ch, num_slots=N + 64) as pub:
        with Subscriber(ch) as sub:
            for _ in range(N):
                pub.send_bytes(raw_payload)
            received = 0
            while received < N:
                m = sub.recv_bytes(timeout=2.0)
                if m:
                    received += 1
    t_raw = time.perf_counter() - t0

    print(
        f"\n[serialization] N={N}: "
        f"pickle={N/t_pickle/1e3:.1f}k msg/s  "
        f"raw_bytes={N/t_raw/1e3:.1f}k msg/s"
    )


# ── Memory usage ──────────────────────────────────────────────────────────────

def test_memory_usage():
    """Check that a channel's overhead is reasonable."""
    from shm_comm.core import segment_size, HEADER_SIZE
    size = segment_size(64, 4096)
    overhead_mb = size / (1024 * 1024)
    print(f"\n[memory] 64 slots × 4096 B = {overhead_mb:.2f} MB per channel")
    assert overhead_mb < 10.0, "Single channel overhead exceeds 10MB"

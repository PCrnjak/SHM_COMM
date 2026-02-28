"""
benchmark.py — End-to-end performance benchmark for shm_comm.

Measures:
  - PUB/SUB throughput for various payload sizes
  - PUB/SUB latency (write-to-read round trip within one process)
  - PUSH/PULL throughput

Usage:
    python examples/benchmark.py
    python examples/benchmark.py --quick   # fewer iterations
"""

import sys
import time
import statistics

QUICK = "--quick" in sys.argv


def fmt_rate(n, elapsed):
    rate = n / elapsed
    if rate >= 1e6:
        return f"{rate/1e6:.2f}M msg/s"
    return f"{rate/1e3:.1f}k msg/s"


def benchmark_pubsub_throughput():
    from shm_comm import Publisher, Subscriber, force_unlink
    from shm_comm.utils import pub_segment_name

    print("\n── PUB/SUB Throughput ─────────────────────────────────────")
    sizes = [64, 512, 1024, 4092] if not QUICK else [64, 512]
    n_msgs = 5_000 if not QUICK else 1_000

    for size in sizes:
        ch = "bench_throughput"
        force_unlink(pub_segment_name(ch))
        payload = b"x" * size
        sent = 0

        with Publisher(ch, num_slots=n_msgs + 64, slot_size=4096) as pub:
            with Subscriber(ch) as sub:
                t0 = time.perf_counter()
                for _ in range(n_msgs):
                    if pub.send_bytes(payload):
                        sent += 1
                t_send = time.perf_counter() - t0

                received = 0
                t0 = time.perf_counter()
                while received < sent:
                    if sub.recv_bytes(timeout=2.0):
                        received += 1
                t_recv = time.perf_counter() - t0

        print(
            f"  {size:5d}B  send={fmt_rate(sent, t_send):>18s}  "
            f"recv={fmt_rate(received, t_recv):>18s}"
        )


def benchmark_pubsub_latency():
    from shm_comm import Publisher, Subscriber, force_unlink
    from shm_comm.utils import pub_segment_name

    print("\n── PUB/SUB Latency (write→read, same process) ─────────────")
    n = 2_000 if not QUICK else 200
    ch = "bench_latency"
    force_unlink(pub_segment_name(ch))

    latencies = []
    with Publisher(ch, num_slots=512, slot_size=128) as pub:
        with Subscriber(ch) as sub:
            for _ in range(n):
                t0 = time.perf_counter_ns()
                pub.send_bytes(b"ping")
                sub.recv_bytes(timeout=1.0)
                latencies.append(time.perf_counter_ns() - t0)

    # Convert to microseconds
    us = [v / 1000 for v in latencies]
    print(
        f"  n={n}  "
        f"min={min(us):.2f}µs  "
        f"p50={statistics.median(us):.2f}µs  "
        f"p99={sorted(us)[int(0.99*n)]:.2f}µs  "
        f"max={max(us):.2f}µs"
    )


def benchmark_pipeline_throughput():
    from shm_comm import Pusher, Puller, force_unlink
    from shm_comm.utils import push_segment_name

    print("\n── PUSH/PULL Throughput ───────────────────────────────────")
    n_msgs = 2_000 if not QUICK else 500
    ch = "bench_pipeline"
    force_unlink(push_segment_name(ch))
    sent = 0

    with Pusher(ch, num_slots=512, slot_size=256) as push:
        with Puller(ch) as pull:
            t0 = time.perf_counter()
            for _ in range(n_msgs):
                if push.send_bytes(b"job"):
                    sent += 1
            t_push = time.perf_counter() - t0

            received = 0
            t0 = time.perf_counter()
            while received < sent:
                if pull.recv_bytes(timeout=2.0):
                    received += 1
            t_pull = time.perf_counter() - t0

    print(
        f"  push={fmt_rate(sent, t_push):>18s}  "
        f"pull={fmt_rate(received, t_pull):>18s}"
    )


if __name__ == "__main__":
    print("shm_comm Benchmark")
    print("=" * 60)

    benchmark_pubsub_throughput()
    benchmark_pubsub_latency()
    benchmark_pipeline_throughput()

    print("\nDone.")

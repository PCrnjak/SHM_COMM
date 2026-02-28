"""
simple_pubsub.py — Minimal publish-subscribe example.

Run the publisher in one terminal:
    python examples/simple_pubsub.py publisher

Run one or more subscribers in other terminals:
    python examples/simple_pubsub.py subscriber
"""

import sys
import time

CHANNEL = "example_pose"


def run_publisher():
    from shm_comm import Publisher

    print("Starting publisher on channel:", CHANNEL)
    with Publisher(CHANNEL, num_slots=64, slot_size=256) as pub:
        seq = 0
        while True:
            msg = {
                "seq": seq,
                "timestamp": time.time(),
                "position": {"x": seq * 0.1, "y": 0.0, "z": 0.5},
            }
            pub.send(msg)
            print(f"  Sent #{seq}: {msg['position']}")
            seq += 1
            time.sleep(0.1)  # 10 Hz


def run_subscriber():
    from shm_comm import Subscriber

    print("Connecting subscriber to channel:", CHANNEL)
    with Subscriber(CHANNEL, timeout_connect=10.0) as sub:
        while True:
            msg = sub.recv(timeout=1.0)
            if msg is None:
                print("  No message (timeout), waiting...")
            else:
                print(f"  Received #{msg['seq']}: {msg['position']}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("publisher", "subscriber"):
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "publisher":
        run_publisher()
    else:
        run_subscriber()

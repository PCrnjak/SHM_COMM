"""
numpy_sharing.py — Zero-copy NumPy array transfer via shared memory.

The publisher sends raw array bytes (no pickle overhead).
The subscriber reconstructs the array with numpy.frombuffer.

Run in two terminals:
    python examples/numpy_sharing.py publisher
    python examples/numpy_sharing.py subscriber
"""

import sys
import time
import struct
import numpy as np

CHANNEL = "example_numpy"
DTYPE = np.float64
SHAPE = (6,)   # 6-DOF joint angles


def pack_array(arr: np.ndarray) -> bytes:
    """Prefix the array bytes with its dtype and shape info."""
    header = struct.pack(">B B", arr.ndim, arr.dtype.itemsize)
    shape_bytes = struct.pack(f">{arr.ndim}I", *arr.shape)
    return header + shape_bytes + arr.tobytes()


def unpack_array(raw: bytes) -> np.ndarray:
    """Reconstruct a numpy array from packed bytes."""
    ndim = raw[0]
    itemsize = raw[1]
    shape = struct.unpack_from(f">{ndim}I", raw, offset=2)
    header_size = 2 + ndim * 4
    dtype = {8: np.float64, 4: np.float32}[itemsize]
    return np.frombuffer(raw[header_size:], dtype=dtype).reshape(shape).copy()


def run_publisher():
    from shm_comm import Publisher

    print(f"Publishing {DTYPE.__name__}{SHAPE} joint arrays on '{CHANNEL}'")
    with Publisher(CHANNEL, num_slots=64, slot_size=512) as pub:
        t = 0.0
        while True:
            joints = np.array([
                np.sin(t + i * 0.5) * 90.0 for i in range(SHAPE[0])
            ], dtype=DTYPE)
            pub.send_bytes(pack_array(joints))
            print(f"  Sent joints: {joints.round(2)}")
            t += 0.1
            time.sleep(0.1)


def run_subscriber():
    from shm_comm import Subscriber

    print(f"Receiving arrays from '{CHANNEL}' …")
    with Subscriber(CHANNEL, timeout_connect=10.0) as sub:
        while True:
            raw = sub.recv_bytes(timeout=1.0)
            if raw is None:
                print("  (waiting…)")
                continue
            arr = unpack_array(raw)
            print(f"  Received joints: {arr.round(2)}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("publisher", "subscriber"):
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "publisher":
        run_publisher()
    else:
        run_subscriber()

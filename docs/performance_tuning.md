# Performance Tuning Guide

## Understanding the Default Configuration

| Parameter | Default | Suitable for |
|-----------|---------|-------------|
| `num_slots` | 64 | Low-rate streams (<1 kHz) |
| `slot_size` | 4096 | Messages up to ~4 KB |
| Poll interval | 100 µs | General robotics loops |

---

## Tuning for Low Latency

### 1. Right-size the slot

The library stores each message in a fixed-size slot.  A slot smaller
than your payload forces a `ValueError`; a slot much larger than your
payload wastes cache lines.

```python
# For a 6-DOF joint state: 6 × float64 = 48 bytes
# Add some header overhead → 128 bytes is plenty
pub = Publisher("joints", slot_size=128)
```

### 2. Increase ring depth for bursty producers

If the producer sends in bursts and the consumer can't keep up, messages
are dropped.  Check `pub.stats()["drop_count"]` after a run.

```python
# High-rate IMU at 1 kHz — give consumers space to breathe
pub = Publisher("imu", num_slots=256, slot_size=64)
```

### 3. Busy-wait in the consumer for absolute minimum latency

The default polling interval is 100 µs.  For sub-100 µs latency set
it to zero (pure busy wait):

```python
# WARNING: consumes 100% of one CPU core
from shm_comm.utils import poll_until
from shm_comm.buffer import read_message_spsc

def recv_busy(shm, tail):
    while True:
        result = read_message_spsc(shm, tail)
        if result:
            data, tail = result
            return data, tail
```

Or reduce the sleep in `poll_until` by patching the call site.

### 4. Use raw bytes / NumPy arrays (zero-copy path)

Bypasses the pickle serializer entirely:

```python
import numpy as np

arr = np.array([1.0, 2.0, 3.0], dtype=np.float64)

pub.send_bytes(arr.tobytes())

# Receiver:
raw = sub.recv_bytes(timeout=0.01)
arr_back = np.frombuffer(raw, dtype=np.float64)
```

See `examples/numpy_sharing.py` for the full pattern.

### 5. Use msgpack for dict-heavy messages

```python
# Requires: pip install msgpack
pub = Publisher("sensors", serialization="msgpack")
sub = Subscriber("sensors", serialization="msgpack")
```

msgpack is typically 2–5× faster than pickle for dictionaries with
numeric values.

---

## Linux-specific Optimisations

### 1. Verify `/dev/shm` is tmpfs

```bash
df -h /dev/shm
# Should show tmpfs (RAM-backed)
```

### 2. Increase `/dev/shm` size if needed

```bash
sudo mount -o remount,size=512M /dev/shm
```

Persisting across reboots: add to `/etc/fstab`:
```
tmpfs /dev/shm tmpfs defaults,size=512M 0 0
```

### 3. CPU pinning and real-time scheduling

For maximum determinism pin the publisher and subscriber to separate
isolated CPU cores and raise the scheduling priority:

```bash
# Pin to cores 2 and 3, FIFO scheduling priority 50
sudo chrt -f 50 taskset -c 2 python my_publisher.py &
sudo chrt -f 50 taskset -c 3 python my_subscriber.py &
```

### 4. Disable CPU frequency scaling

```bash
sudo cpupower frequency-set --governor performance
```

---

## Windows-specific Notes

- Shared memory on Windows uses named file mappings (slower than Linux tmpfs).
- The file lock (`sync.FileLock`) uses `msvcrt.locking` which is process-safe.
- Expect 2–5× higher latency compared to Linux due to OS overhead.
- Run the benchmark to establish a baseline: `python examples/benchmark.py`

---

## macOS-specific Notes

Default shared memory limits are very small on macOS:

```bash
# Check current limits
sysctl kern.sysv.shmmax kern.sysv.shmall

# Increase (example: 256 MB)
sudo sysctl -w kern.sysv.shmmax=268435456
sudo sysctl -w kern.sysv.shmall=65536
```

To persist add to `/etc/sysctl.conf`.

---

## Profiling

Run the built-in benchmark to identify bottlenecks:

```bash
python examples/benchmark.py

# Quick mode (fewer iterations)
python examples/benchmark.py --quick
```

Run performance tests with verbose output:

```bash
pytest tests/test_performance.py -v -s
```

---

## Checklist

- [ ] `slot_size` matches your typical message size (±50%)
- [ ] `num_slots` is large enough that `drop_count` stays near zero
- [ ] Using `send_bytes` / `recv_bytes` for NumPy arrays
- [ ] Consumer process is scheduled with adequate CPU time
- [ ] `/dev/shm` is tmpfs and has enough space (Linux)
- [ ] No unnecessary serialisation on the critical path

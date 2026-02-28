# shm-comm

High-performance shared memory IPC for Python — ZMQ-like API without the network overhead.

[![CI](https://github.com/PetarKovacevic/shm-comm/actions/workflows/ci.yml/badge.svg)](https://github.com/PetarKovacevic/shm-comm/actions)
[![PyPI](https://img.shields.io/pypi/v/shm-comm)](https://pypi.org/project/shm-comm/)
[![Python](https://img.shields.io/pypi/pyversions/shm-comm)](https://pypi.org/project/shm-comm/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A ZMQ/TCP-style Python IPC library using **shared memory** for ultra-low
latency inter-process communication on the same machine.

Designed for robotics applications where microsecond-level latency
matters and TCP/ZMQ network overhead is unacceptable.

---

## Features

- **PUB/SUB** — broadcast to multiple independent subscribers
- **REQ/REP** — synchronous request-reply service calls
- **PUSH/PULL** — work-queue distribution across multiple workers
- ZMQ-like API — easy to learn if you know ZMQ
- Pickle and msgpack serialization (raw bytes / NumPy zero-copy)
- Cross-platform: Linux (primary), Windows, macOS
- No external C dependencies — pure Python + NumPy
- Comprehensive error handling and logging

## Performance

| Transport | Latency p50 | Throughput | Notes |
|---|---|---|---|
| ZMQ TCP (localhost) | ~80–200µs | ~500k msg/s | Kernel network stack |
| ZMQ IPC (Unix socket) | ~15–50µs | ~1–3M msg/s | Linux only |
| **shm-comm (Windows)** | **~4–10µs** | **~250–500k msg/s** | This library |
| **shm-comm (Linux)** | **<5µs** | **>500k msg/s** | This library |

**10–20× lower latency than ZMQ TCP** on the same machine.

Run the benchmark yourself:
```bash
python examples/benchmark.py
python examples/benchmark.py --quick   # faster, fewer iterations
```

---

## Installation

```bash
pip install shm-comm

# Optional: faster serialization for numeric data
pip install shm-comm[msgpack]
```

Or install from source for development:

```bash
git clone https://github.com/PetarKovacevic/shm-comm.git
cd shm-comm
pip install -e .[dev]
```

**Requirements:** Python 3.8+, NumPy.

---

## Quick Start

### Publish / Subscribe

```python
# publisher.py
from shm_comm import Publisher
import time

with Publisher("robot/pose") as pub:
    t = 0
    while True:
        pub.send({"x": t * 0.1, "y": 0.0, "heading": t * 0.01})
        t += 1
        time.sleep(0.01)   # 100 Hz
```

```python
# subscriber.py
from shm_comm import Subscriber

with Subscriber("robot/pose") as sub:
    while True:
        pose = sub.recv(timeout=1.0)
        if pose:
            print(f"x={pose['x']:.2f}  heading={pose['heading']:.3f}")
```

### Request / Reply

```python
# server.py
from shm_comm import Replier

with Replier("arm/control") as rep:
    while True:
        req = rep.recv(timeout=5.0)
        if req:
            rep.send({"status": "ok", "echo": req})
```

```python
# client.py
from shm_comm import Requester

with Requester("arm/control") as req:
    reply = req.request({"command": "get_status"}, timeout=2.0)
    print(reply)
```

### Push / Pull (Work Queue)

```python
# pusher.py
from shm_comm import Pusher

with Pusher("jobs") as push:
    for job in my_jobs:
        push.send(job)
```

```python
# worker.py  (run multiple copies)
from shm_comm import Puller

with Puller("jobs") as pull:
    while True:
        job = pull.recv(timeout=1.0)
        if job:
            process(job)
```

### NumPy Zero-Copy

```python
import numpy as np
from shm_comm import Publisher, Subscriber

pub = Publisher("joints", slot_size=256)
pub.send_bytes(joint_array.tobytes())

sub = Subscriber("joints")
raw = sub.recv_bytes(timeout=0.1)
joints = np.frombuffer(raw, dtype=np.float64)
```

---

## Running the Examples

```bash
# Terminal 1
python examples/simple_pubsub.py publisher

# Terminal 2
python examples/simple_pubsub.py subscriber

# Terminal 1
python examples/reqrep_example.py server

# Terminal 2
python examples/reqrep_example.py client
```

---

## Running Tests

```bash
# All unit tests (fast, in-process)
pytest tests/ -v

# Skip multi-process tests (faster)
pytest tests/ -v -m "not multiprocess"

# Performance benchmarks (with printed output)
pytest tests/test_performance.py -v -s

# Individual test files
pytest tests/test_core.py -v
pytest tests/test_buffer.py -v
pytest tests/test_pubsub.py -v
pytest tests/test_reqrep.py -v
pytest tests/test_pipeline.py -v
```

---

## Project Structure

```
Shared_memory_comms_lib/
├── shm_comm/                   # Library source
│   ├── __init__.py             # Public API
│   ├── core.py                 # SHM segment lifecycle
│   ├── buffer.py               # Lock-free ring buffer
│   ├── serialize.py            # Pickle / msgpack
│   ├── sync.py                 # Cross-process file lock
│   ├── utils.py                # Helpers & utilities
│   └── patterns/
│       ├── pubsub.py           # Publisher / Subscriber
│       ├── reqrep.py           # Requester / Replier
│       └── pipeline.py         # Pusher / Puller
├── tests/
│   ├── conftest.py
│   ├── test_core.py
│   ├── test_buffer.py
│   ├── test_pubsub.py
│   ├── test_reqrep.py
│   ├── test_pipeline.py
│   └── test_performance.py
├── examples/
│   ├── simple_pubsub.py
│   ├── reqrep_example.py
│   ├── numpy_sharing.py
│   └── benchmark.py
├── docs/
│   ├── api_reference.md
│   ├── performance_tuning.md
│   └── troubleshooting.md
├── setup.py
├── requirements.txt
├── pytest.ini
└── README.md
```

---

## How It Works

Each channel maps to a named shared memory segment containing:

1. **A 128-byte header** with head/tail pointers and statistics (read/written
   as NumPy `int64` arrays — atomic on all 64-bit platforms).
2. **A ring buffer** of fixed-size slots, each holding a 4-byte size prefix
   followed by the payload.

**PUB/SUB**: Subscribers maintain a private local tail — zero coordination,
zero locking.  Slow subscribers transparently skip old messages.

**REQ/REP**: Two SPSC channels (one per direction).  No locking needed.

**PUSH/PULL**: Pullers compete for the shared tail pointer using a lightweight
cross-process file lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows).

---

## Documentation

- [API Reference](docs/api_reference.md)
- [Performance Tuning](docs/performance_tuning.md)
- [Troubleshooting](docs/troubleshooting.md)

---

## Compared to ZMQ

| Feature | ZMQ | shm-comm |
|---|---|---|
| Same-machine latency | ~80–200µs | **~4–10µs** |
| PUB/SUB | ✅ | ✅ |
| REQ/REP | ✅ | ✅ |
| PUSH/PULL | ✅ | ✅ |
| Cross-machine (networked) | ✅ | ❌ Same machine only |
| Language interop | Many languages | Python only |
| Zero pip dependencies | ❌ | ✅ (only NumPy) |

## Platform Support

| Platform | Status | Notes |
|---|---|---|
| Linux | ✅ Primary | `/dev/shm` backed by RAM, fastest |
| Windows | ✅ Supported | Named memory-mapped files |
| macOS | ✅ Supported | May need SHM limit increase |

## License

MIT — see [LICENSE](LICENSE)

# API Reference

## Patterns

### Publisher / Subscriber (PUB/SUB)

```python
from shm_comm import Publisher, Subscriber
```

#### `Publisher(name, num_slots=64, slot_size=4096, serialization="pickle")`

Creates a shared memory ring buffer and acts as the sole writer.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | str | — | Channel name (any valid string) |
| `num_slots` | int | 64 | Depth of the ring buffer |
| `slot_size` | int | 4096 | Bytes per slot (payload max = `slot_size - 4`) |
| `serialization` | str | `"pickle"` | `"pickle"` or `"msgpack"` |

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `send(data, *, block=False, timeout=None)` | `bool` | Serialize and publish an object |
| `send_bytes(payload, *, block=False, timeout=None)` | `bool` | Publish raw bytes (zero-copy) |
| `stats()` | `dict` | Ring buffer statistics |
| `close()` | `None` | Destroy the segment |

---

#### `Subscriber(name, timeout_connect=5.0, serialization="pickle")`

Attaches to an existing publisher segment. Each instance has its own
private read cursor — multiple subscribers are fully independent.

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `recv(timeout=None)` | `object \| None` | Block until a message arrives or timeout |
| `recv_bytes(timeout=None)` | `bytes \| None` | Same, returns raw bytes |
| `stats()` | `dict` | Statistics including `local_tail` |
| `close()` | `None` | Detach from the segment |

---

### Requester / Replier (REQ/REP)

```python
from shm_comm import Replier, Requester
```

#### `Replier(name, num_slots=16, slot_size=8192, serialization="pickle")`

**Must be started before the Requester.** Creates both
`shmcomm_req_{name}` and `shmcomm_rep_{name}` segments.

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `recv(timeout=None)` | `object \| None` | Wait for a request |
| `send(data)` | `bool` | Send reply (call after `recv`) |
| `send_bytes(payload)` | `bool` | Send raw bytes reply |
| `close()` | `None` | Destroy both segments |

---

#### `Requester(name, timeout_connect=5.0, serialization="pickle")`

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `send(data)` | `bool` | Send a request |
| `recv(timeout=None)` | `object \| None` | Wait for the reply |
| `request(data, timeout=5.0)` | `object` | Send + recv in one call. Raises `SHMTimeoutError` on timeout |
| `close()` | `None` | Detach |

---

### Pusher / Puller (PUSH/PULL)

```python
from shm_comm import Pusher, Puller
```

#### `Pusher(name, num_slots=128, slot_size=4096, serialization="pickle")`

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `send(data, *, block=True, timeout=None)` | `bool` | Push a work item |
| `send_bytes(payload, *, block=True, timeout=None)` | `bool` | Push raw bytes |
| `stats()` | `dict` | Statistics |
| `close()` | `None` | Destroy the segment |

---

#### `Puller(name, timeout_connect=5.0, serialization="pickle")`

Multiple Pullers compete for messages. Each message goes to exactly one Puller.
A cross-process file lock coordinates tail advancement.

**Methods**

| Method | Returns | Description |
|--------|---------|-------------|
| `recv(timeout=None)` | `object \| None` | Claim and return the next work item |
| `recv_bytes(timeout=None)` | `bytes \| None` | Claim raw bytes |
| `stats()` | `dict` | Statistics |
| `close()` | `None` | Detach |

---

## Exceptions

```python
from shm_comm import (
    SHMError,
    SHMConnectionError,
    SHMTimeoutError,
    SHMBufferFullError,
    SHMSerializationError,
)
```

| Exception | When raised |
|-----------|-------------|
| `SHMError` | Base class for all shm_comm errors |
| `SHMConnectionError` | Cannot create or attach to a segment |
| `SHMTimeoutError` | Blocking operation exceeded its timeout |
| `SHMBufferFullError` | Non-blocking send on a full buffer |
| `SHMSerializationError` | pickle / msgpack serialization failure |

---

## Utilities

```python
from shm_comm import force_unlink, list_segments
```

### `force_unlink(name: str) → bool`

Forcibly destroy a shared memory segment by its OS-level name
(e.g. `"shmcomm_pub_sensors"`). Returns `True` if the segment existed.

### `list_segments() → list[str]`

List all `shmcomm_*` segments visible in `/dev/shm` (Linux only).

---

## Serialization

```python
from shm_comm.serialize import serialize, deserialize
```

### `serialize(obj, method="pickle") → bytes`

Serialize any Python object. Pass `method="msgpack"` for better
performance on numeric-heavy data (requires `pip install msgpack`).

### `deserialize(data, method="pickle") → object`

Deserialize bytes back to a Python object.

---

## Memory Layout

Each channel occupies one shared memory segment with this layout:

```
Bytes     Field         Notes
──────────────────────────────────────────────────────────────────
 0 -  7   MAGIC         0x53484D434F4D4D31  ("SHMCOMM1")
 8 - 15   VERSION       1
16 - 23   HEAD          Next write slot (advanced by producer)
24 - 31   TAIL          Shared read cursor (push/pull only)
32 - 39   MSG_COUNT     Total messages written
40 - 47   DROP_COUNT    Messages dropped (buffer full)
48 - 55   NUM_SLOTS     Ring buffer depth
56 - 63   SLOT_SIZE     Bytes per slot
64 -127   RESERVED
128+      Data slots    Each slot: [size:uint32][payload]
```

**Segment size** = `128 + num_slots × slot_size` bytes.

Default per channel: `128 + 64 × 4096 = 262,272 bytes ≈ 256 KB`.

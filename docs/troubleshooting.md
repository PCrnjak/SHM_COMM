# Troubleshooting Guide

## `SHMConnectionError: Shared memory segment '...' did not appear`

**Symptom**: Subscriber/Requester/Puller raises this on startup.

**Cause**: The publisher/server has not created the shared memory segment yet.

**Fixes**:
1. Ensure the publisher/server is running *before* the subscriber/client.
2. Increase `timeout_connect`:
   ```python
   sub = Subscriber("channel", timeout_connect=30.0)
   ```
3. Check for stale segments (see "Stale Segments" below) and force-clean them.

---

## `SHMConnectionError: invalid magic`

**Symptom**: Attaching to an existing segment fails with a bad magic number.

**Cause**: A non-shm_comm segment has the same name (naming collision), or the
segment is from an older version of the library.

**Fix**:
```python
from shm_comm import force_unlink
force_unlink("shmcomm_pub_my_channel")
# Then restart the publisher
```

---

## Stale Segments After Crashes

If a process is killed before calling `close()`, the shared memory
segment is not destroyed (it persists until explicitly unlinked or
the machine reboots — on Linux; Windows cleans up on process exit).

**Check for stale segments (Linux)**:
```bash
ls /dev/shm/ | grep shmcomm
```

**Remove them**:
```bash
# Remove all shm_comm segments
ls /dev/shm/ | grep shmcomm | xargs -I{} rm /dev/shm/{}
```

Or from Python:
```python
from shm_comm import force_unlink, list_segments

for seg in list_segments():
    force_unlink(seg)
    print(f"Removed: {seg}")
```

The publisher also removes any stale segment with the same name automatically
on startup (via `create_segment`).

---

## Messages Being Dropped

**Symptom**: `pub.stats()["drop_count"]` keeps increasing.

**Cause**: The consumer isn't reading fast enough; the ring buffer wraps around.

**Fixes**:
1. Increase `num_slots`:
   ```python
   pub = Publisher("fast_channel", num_slots=512)
   ```
2. Speed up the subscriber loop (reduce processing time per message).
3. If drops are acceptable (e.g. live video frames), this is normal behavior.

---

## `ValueError: Payload size N exceeds slot capacity M`

**Cause**: A message is larger than `slot_size - 4` bytes.

**Fix**: Increase `slot_size` when creating the Publisher/Pusher:
```python
pub = Publisher("big_messages", slot_size=65536)  # 64 KB slots
```

Note: The segment size increases proportionally.
`segment_size = 128 + num_slots × slot_size`

---

## `SHMSerializationError: pickle failed`

**Cause**: The object you're trying to send cannot be pickled (e.g. lambdas,
file handles, sockets, database connections).

**Fixes**:
1. Convert the object to a picklable form (dict, list, numpy array).
2. Use `send_bytes()` with manual serialization.
3. Switch to `msgpack` for simple data structures:
   ```python
   pub = Publisher("ch", serialization="msgpack")
   ```

---

## Subscriber Receives No Messages

**Symptom**: `sub.recv()` always times out despite the publisher running.

**Common causes**:

1. **Subscriber started after publisher, starting at `head`**: New subscribers
   start from the *current* head and only receive future messages. This is
   by design. If you need history, start the subscriber before the publisher.

2. **Wrong channel name**: Double-check that `Publisher("name")` and
   `Subscriber("name")` use identical strings.

3. **Serialization mismatch**: Publisher uses `"msgpack"` but subscriber uses
   `"pickle"` (default). Set `serialization` identically on both sides.

---

## High Latency or CPU Usage

See the [Performance Tuning Guide](performance_tuning.md) for detailed steps.

Quick checklist:
- Use `send_bytes` / `recv_bytes` to skip serialization
- Increase `num_slots` to prevent drops
- On Linux: verify `/dev/shm` is tmpfs (`df -h /dev/shm`)
- Use CPU pinning for consistent latency

---

## Windows: `PermissionError` on `FileLock`

**Cause**: `msvcrt.locking` requires exclusive file access; another process
may be holding the lock file open.

**Fix**: Remove stale lock files from `%TEMP%`:
```powershell
Remove-Item $env:TEMP\shmcomm_*.lock -ErrorAction SilentlyContinue
```

---

## macOS: `OSError: [Errno 12] Cannot allocate memory`

**Cause**: macOS shared memory limits are very small by default.

**Fix**: Increase them (see [Performance Tuning — macOS](performance_tuning.md#macos-specific-notes)).

---

## Enabling Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("shmcomm").setLevel(logging.DEBUG)
```

This prints every slot read/write, segment create/destroy, and lock
acquire/release — useful for diagnosing timing issues.

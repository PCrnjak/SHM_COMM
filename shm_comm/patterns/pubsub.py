"""
Publish-Subscribe pattern for shm_comm.

One publisher writes to a ring buffer; any number of subscribers each
maintain a *private* read cursor, so they never coordinate with each
other or with the publisher.  A slow subscriber simply misses old
messages once the ring wraps — this is intentional.

Usage::

    # Process A — publisher
    from shm_comm.patterns.pubsub import Publisher

    pub = Publisher("robot/pose")
    pub.send({"x": 1.0, "y": 2.0, "heading": 0.5})
    pub.close()                # or use as context manager

    # Process B — subscriber
    from shm_comm.patterns.pubsub import Subscriber

    with Subscriber("robot/pose") as sub:
        while True:
            msg = sub.recv(timeout=1.0)   # None → timed out (no-throw)
            if msg is not None:
                print(msg)
"""

import time
import atexit
import logging
from multiprocessing import shared_memory

from ..core import create_segment, attach_segment, close_segment
from ..buffer import write_message, read_message_spsc, get_stats
from ..serialize import serialize, deserialize
from ..utils import pub_segment_name, poll_until
from ..exceptions import SHMTimeoutError, SHMConnectionError

logger = logging.getLogger("shmcomm.pubsub")

# Default ring-buffer geometry
_DEFAULT_NUM_SLOTS = 64
_DEFAULT_SLOT_SIZE = 4096   # bytes per slot (payload + 4-byte size prefix)


class Publisher:
    """Writes messages to a named shared-memory channel.

    Args:
        name:      Channel name (e.g. ``"robot/pose"``).
        num_slots: Number of ring-buffer slots.
        slot_size: Max bytes per message (overhead: 4 bytes per slot).
        serialization: ``"pickle"`` (default) or ``"msgpack"``.

    Example::

        pub = Publisher("sensors/imu", num_slots=128, slot_size=1024)
        pub.send(imu_dict)
        pub.close()
    """

    def __init__(
        self,
        name: str,
        num_slots: int = _DEFAULT_NUM_SLOTS,
        slot_size: int = _DEFAULT_SLOT_SIZE,
        serialization: str = "pickle",
    ):
        self._name = name
        self._serialization = serialization
        self._shm_name = pub_segment_name(name)
        self._shm: shared_memory.SharedMemory = create_segment(
            self._shm_name, num_slots, slot_size
        )
        atexit.register(self._atexit_close)
        logger.info(
            "Publisher('%s') ready — %d slots × %d bytes", name, num_slots, slot_size
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, data, *, block: bool = False, timeout: float | None = None) -> bool:
        """Serialize and publish *data*.

        Uses ``overwrite=True`` so the publisher never blocks — if slow
        subscribers lag behind, they silently skip stale messages.

        Args:
            data:    Any serializable Python object.
            block:   Ignored (kept for API compatibility).
            timeout: Ignored (kept for API compatibility).

        Returns:
            ``True`` always (PUB/SUB is non-blocking by design).

        Raises:
            SHMSerializationError: *data* cannot be serialized.

        Example::

            pub.send({"cmd": "stop"})
        """
        payload = serialize(data, method=self._serialization)
        return write_message(self._shm, payload, overwrite=True)

    def send_bytes(
        self, payload: bytes, *, block: bool = False, timeout: float | None = None
    ) -> bool:
        """Publish raw bytes without serialization (zero-copy path).

        Example::

            pub.send_bytes(numpy_array.tobytes())
        """
        return write_message(self._shm, payload, overwrite=True)

    def stats(self) -> dict:
        """Return a snapshot of ring-buffer statistics.

        Returns:
            Dict with keys: ``head``, ``tail``, ``num_slots``,
            ``slot_size``, ``msg_count``, ``drop_count``,
            ``used_slots``, ``free_slots``.
        """
        return get_stats(self._shm)

    def close(self) -> None:
        """Release and destroy the shared memory segment.

        Call this when the publisher is done.  Subscribers that are
        still attached will fail gracefully on their next recv.
        """
        if self._shm is not None:
            close_segment(self._shm, destroy=True)
            self._shm = None
            logger.info("Publisher('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Publisher":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _atexit_close(self) -> None:
        if self._shm is not None:
            self.close()

    def __repr__(self) -> str:
        return f"Publisher(name={self._name!r})"


class Subscriber:
    """Reads messages from a named shared-memory channel.

    Each Subscriber instance has its own private read cursor (tail) so
    multiple subscribers can coexist without coordination.

    Args:
        name:              Channel name — must match the publisher.
        timeout_connect:   Seconds to wait for the publisher to create
                           the segment before raising
                           :class:`~shm_comm.exceptions.SHMConnectionError`.
        serialization:     Must match the publisher's serialization method.

    Example::

        with Subscriber("sensors/imu", timeout_connect=10.0) as sub:
            msg = sub.recv(timeout=0.5)
    """

    def __init__(
        self,
        name: str,
        timeout_connect: float = 5.0,
        serialization: str = "pickle",
    ):
        self._name = name
        self._serialization = serialization
        self._shm_name = pub_segment_name(name)
        self._shm: shared_memory.SharedMemory = attach_segment(
            self._shm_name, timeout=timeout_connect
        )
        # Private cursor — starts at current head so we only receive
        # *new* messages (not the historical backlog).
        from ..core import get_header, IDX_HEAD
        hdr = get_header(self._shm)
        self._tail: int = int(hdr[IDX_HEAD])
        atexit.register(self._atexit_close)
        logger.info("Subscriber('%s') attached, starting tail=%d", name, self._tail)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recv(self, timeout: float | None = None):
        """Wait for the next message and return the deserialized object.

        Args:
            timeout: Seconds to wait. ``None`` = block indefinitely.
                     Pass ``0`` for a pure non-blocking poll.

        Returns:
            The deserialized Python object, or ``None`` if no message
            arrived within *timeout*.

        Example::

            pose = sub.recv(timeout=0.1)
            if pose:
                robot.update(pose)
        """
        result = poll_until(self._try_recv, timeout=timeout)
        return result  # None on timeout

    def recv_bytes(self, timeout: float | None = None) -> bytes | None:
        """Like :meth:`recv` but returns raw bytes without deserialization."""
        result = poll_until(self._try_recv_bytes, timeout=timeout)
        return result

    def stats(self) -> dict:
        """Return a snapshot of ring-buffer statistics for this subscriber.

        The ``tail`` in the returned dict is the *publisher's* shared
        tail; ``local_tail`` is this subscriber's private cursor.
        """
        s = get_stats(self._shm)
        s["local_tail"] = self._tail
        return s

    def close(self) -> None:
        """Detach from the shared memory segment."""
        if self._shm is not None:
            close_segment(self._shm, destroy=False)
            self._shm = None
            logger.info("Subscriber('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Subscriber":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _try_recv(self):
        result = read_message_spsc(self._shm, self._tail)
        if result is None:
            return None
        raw, new_tail = result
        self._tail = new_tail
        return deserialize(raw, method=self._serialization)

    def _try_recv_bytes(self):
        result = read_message_spsc(self._shm, self._tail)
        if result is None:
            return None
        raw, new_tail = result
        self._tail = new_tail
        return raw

    def _atexit_close(self) -> None:
        if self._shm is not None:
            self.close()

    def __repr__(self) -> str:
        return f"Subscriber(name={self._name!r}, tail={self._tail})"

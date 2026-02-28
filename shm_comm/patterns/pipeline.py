"""
Push-Pull (pipeline) pattern for shm_comm.

One Pusher writes messages into a ring buffer; multiple Pullers compete
for those messages.  Each message is delivered to exactly *one* Puller
(load-balanced distribution).

A cross-process :class:`~shm_comm.sync.FileLock` serialises the tail
pointer advancement so two Pullers cannot claim the same slot.

Usage::

    # Process A — work producer
    from shm_comm.patterns.pipeline import Pusher

    with Pusher("work_queue") as push:
        for item in work_items:
            push.send(item)

    # Processes B, C, … — workers
    from shm_comm.patterns.pipeline import Puller

    with Puller("work_queue") as pull:
        while True:
            job = pull.recv(timeout=1.0)
            if job:
                process(job)
"""

import atexit
import logging
from multiprocessing import shared_memory

from ..core import create_segment, attach_segment, close_segment
from ..buffer import write_message, read_message_shared_tail, get_stats
from ..serialize import serialize, deserialize
from ..sync import FileLock
from ..utils import push_segment_name, poll_until
from ..exceptions import SHMTimeoutError

logger = logging.getLogger("shmcomm.pipeline")

_DEFAULT_NUM_SLOTS = 128
_DEFAULT_SLOT_SIZE = 4096


class Pusher:
    """Writes work items into a named push/pull channel.

    Args:
        name:          Channel name.
        num_slots:     Ring-buffer depth.
        slot_size:     Max bytes per message.
        serialization: ``"pickle"`` (default) or ``"msgpack"``.

    Example::

        push = Pusher("jobs", num_slots=256)
        push.send({"task": "calibrate", "axis": 3})
        push.close()
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
        self._shm_name = push_segment_name(name)
        self._shm: shared_memory.SharedMemory = create_segment(
            self._shm_name, num_slots, slot_size
        )
        atexit.register(self._atexit_close)
        logger.info(
            "Pusher('%s') ready — %d slots × %d bytes", name, num_slots, slot_size
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, data, *, block: bool = True, timeout: float | None = None) -> bool:
        """Push *data* onto the queue.

        Args:
            data:    Any serializable Python object.
            block:   Block if the buffer is full (default True —
                     push should rarely drop).
            timeout: Seconds to wait when *block* is ``True``.

        Returns:
            ``True`` on success, ``False`` if full and block=False.

        Raises:
            SHMBufferFullError: block=True and timeout expired.

        Example::

            push.send(job_dict)
        """
        payload = serialize(data, method=self._serialization)
        return write_message(self._shm, payload, block=block, timeout=timeout)

    def send_bytes(
        self, payload: bytes, *, block: bool = True, timeout: float | None = None
    ) -> bool:
        """Push raw bytes (zero-copy path)."""
        return write_message(self._shm, payload, block=block, timeout=timeout)

    def stats(self) -> dict:
        """Return ring-buffer statistics."""
        return get_stats(self._shm)

    def close(self) -> None:
        """Destroy the shared memory segment."""
        if self._shm is not None:
            close_segment(self._shm, destroy=True)
            self._shm = None
            logger.info("Pusher('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Pusher":
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
        return f"Pusher(name={self._name!r})"


class Puller:
    """Pulls work items from a named push/pull channel.

    Multiple Puller instances compete for messages; each message is
    delivered to exactly one Puller.  A file lock ensures that two
    Pullers never claim the same slot.

    Args:
        name:              Channel name (must match the Pusher).
        timeout_connect:   Seconds to wait for the Pusher to start.
        serialization:     Must match the Pusher.

    Example::

        with Puller("jobs") as pull:
            job = pull.recv(timeout=2.0)
    """

    def __init__(
        self,
        name: str,
        timeout_connect: float = 5.0,
        serialization: str = "pickle",
    ):
        self._name = name
        self._serialization = serialization
        self._shm_name = push_segment_name(name)
        self._shm: shared_memory.SharedMemory = attach_segment(
            self._shm_name, timeout=timeout_connect
        )
        # FileLock shared among all Puller instances on this machine.
        self._lock = FileLock(self._shm_name)
        atexit.register(self._atexit_close)
        logger.info("Puller('%s') connected", name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recv(self, timeout: float | None = None):
        """Claim and return the next available work item.

        Args:
            timeout: Seconds to wait. ``None`` = block indefinitely.
                     ``0`` = non-blocking poll.

        Returns:
            Deserialized object, or ``None`` on timeout.

        Example::

            job = pull.recv(timeout=1.0)
            if job:
                run_job(job)
        """
        result = poll_until(self._try_claim, timeout=timeout)
        return result

    def recv_bytes(self, timeout: float | None = None) -> bytes | None:
        """Like :meth:`recv` but returns raw bytes."""
        result = poll_until(self._try_claim_bytes, timeout=timeout)
        return result

    def stats(self) -> dict:
        """Return ring-buffer statistics."""
        return get_stats(self._shm)

    def close(self) -> None:
        """Detach from the shared memory segment."""
        if self._shm is not None:
            close_segment(self._shm, destroy=False)
            self._shm = None
            logger.info("Puller('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Puller":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_claim(self):
        """Atomically claim one slot under the file lock."""
        with self._lock:
            raw = read_message_shared_tail(self._shm)
        if raw is None:
            return None
        return deserialize(raw, method=self._serialization)

    def _try_claim_bytes(self):
        with self._lock:
            return read_message_shared_tail(self._shm)

    def _atexit_close(self) -> None:
        if self._shm is not None:
            self.close()

    def __repr__(self) -> str:
        return f"Puller(name={self._name!r})"

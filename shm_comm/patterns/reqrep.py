"""
Request-Reply pattern for shm_comm.

A single Requester sends a message and waits for exactly one reply from
a single Replier.  This gives you the semantics of ZMQ REQ/REP without
any network overhead.

Two shared-memory segments are used:

    ``shmcomm_req_{name}``  — client → server (requests)
    ``shmcomm_rep_{name}``  — server → client (replies)

Both are SPSC (single-producer single-consumer) ring buffers so no
locking is required on the critical path.

Usage::

    # Process A — server
    from shm_comm.patterns.reqrep import Replier

    with Replier("control") as rep:
        while True:
            request = rep.recv(timeout=5.0)
            if request is not None:
                rep.send({"status": "ok", "echo": request})

    # Process B — client
    from shm_comm.patterns.reqrep import Requester

    with Requester("control") as req:
        req.send({"command": "ping"})
        response = req.recv(timeout=2.0)
        print(response)
"""

import atexit
import logging
from multiprocessing import shared_memory

from ..core import create_segment, attach_segment, close_segment
from ..buffer import write_message, read_message_spsc, get_stats
from ..serialize import serialize, deserialize
from ..utils import req_segment_name, rep_segment_name, poll_until
from ..exceptions import SHMTimeoutError

logger = logging.getLogger("shmcomm.reqrep")

_DEFAULT_NUM_SLOTS = 16    # request-reply is typically low-volume
_DEFAULT_SLOT_SIZE = 8192  # allow larger messages for service responses


class Replier:
    """Server-side of a request-reply exchange.

    The Replier *creates* both shared-memory segments (request and
    reply channels), so it must be started before the Requester.

    Args:
        name:          Service name.  Requester must use the same name.
        num_slots:     Ring-buffer depth (requests and replies share the
                       same geometry).
        slot_size:     Max bytes per message.
        serialization: ``"pickle"`` (default) or ``"msgpack"``.

    Example::

        rep = Replier("arm/controller")
        request = rep.recv(timeout=10.0)
        rep.send({"ack": True})
        rep.close()
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

        req_name = req_segment_name(name)
        rep_name = rep_segment_name(name)

        self._req_shm: shared_memory.SharedMemory = create_segment(
            req_name, num_slots, slot_size
        )
        self._rep_shm: shared_memory.SharedMemory = create_segment(
            rep_name, num_slots, slot_size
        )

        self._req_tail: int = 0  # private read cursor on req channel
        atexit.register(self._atexit_close)
        logger.info("Replier('%s') ready", name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recv(self, timeout: float | None = None):
        """Wait for the next request.

        Args:
            timeout: Seconds to wait. ``None`` = block indefinitely.
                     ``0`` = non-blocking poll.

        Returns:
            Deserialized request object, or ``None`` on timeout.

        Example::

            request = rep.recv(timeout=5.0)
        """
        result = poll_until(self._try_recv, timeout=timeout)
        return result

    def send(self, data) -> bool:
        """Send a reply.

        Must be called *after* :meth:`recv` returns a request.

        Args:
            data: Any serializable Python object.

        Returns:
            ``True`` on success.

        Raises:
            SHMBufferFullError: The reply buffer is full.

        Example::

            rep.send({"status": "ok"})
        """
        payload = serialize(data, method=self._serialization)
        return write_message(self._rep_shm, payload)

    def send_bytes(self, payload: bytes) -> bool:
        """Send raw bytes as a reply (zero-copy path)."""
        return write_message(self._rep_shm, payload)

    def recv_bytes(self, timeout: float | None = None) -> bytes | None:
        """Wait for the next request and return it as raw bytes.

        Use when the Requester sent with :meth:`~Requester.send_bytes`.
        """
        result = poll_until(self._try_recv_bytes, timeout=timeout)
        return result

    def close(self) -> None:
        """Destroy both shared memory segments."""
        for attr in ("_req_shm", "_rep_shm"):
            shm = getattr(self, attr, None)
            if shm is not None:
                close_segment(shm, destroy=True)
                setattr(self, attr, None)
        logger.info("Replier('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Replier":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_recv(self):
        result = read_message_spsc(self._req_shm, self._req_tail)
        if result is None:
            return None
        raw, new_tail = result
        self._req_tail = new_tail
        return deserialize(raw, method=self._serialization)

    def _try_recv_bytes(self):
        result = read_message_spsc(self._req_shm, self._req_tail)
        if result is None:
            return None
        raw, new_tail = result
        self._req_tail = new_tail
        return raw

    def _atexit_close(self) -> None:
        for attr in ("_req_shm", "_rep_shm"):
            if getattr(self, attr, None) is not None:
                self.close()
                break

    def __repr__(self) -> str:
        return f"Replier(name={self._name!r})"


class Requester:
    """Client-side of a request-reply exchange.

    The Requester *attaches* to the segments created by the
    :class:`Replier`, so start the Replier first.

    Args:
        name:            Service name (must match the Replier).
        timeout_connect: Seconds to wait for the Replier to start.
        serialization:   Must match the Replier.

    Example::

        req = Requester("arm/controller")
        req.send({"command": "get_position"})
        resp = req.recv(timeout=1.0)
        print(resp)
        req.close()
    """

    def __init__(
        self,
        name: str,
        timeout_connect: float = 5.0,
        serialization: str = "pickle",
    ):
        self._name = name
        self._serialization = serialization

        req_name = req_segment_name(name)
        rep_name = rep_segment_name(name)

        self._req_shm: shared_memory.SharedMemory = attach_segment(
            req_name, timeout=timeout_connect
        )
        self._rep_shm: shared_memory.SharedMemory = attach_segment(
            rep_name, timeout=timeout_connect
        )

        self._rep_tail: int = 0  # private read cursor on rep channel
        atexit.register(self._atexit_close)
        logger.info("Requester('%s') connected", name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, data) -> bool:
        """Send a request to the server.

        Args:
            data: Any serializable Python object.

        Returns:
            ``True`` on success.

        Raises:
            SHMBufferFullError: The request buffer is full.

        Example::

            req.send({"query": "status"})
        """
        payload = serialize(data, method=self._serialization)
        return write_message(self._req_shm, payload)

    def send_bytes(self, payload: bytes) -> bool:
        """Send raw bytes as a request (zero-copy path)."""
        return write_message(self._req_shm, payload)

    def recv(self, timeout: float | None = None):
        """Wait for the reply to the last request.

        Args:
            timeout: Seconds to wait. ``None`` = block indefinitely.

        Returns:
            Deserialized reply object, or ``None`` on timeout.

        Example::

            reply = req.recv(timeout=2.0)
        """
        result = poll_until(self._try_recv, timeout=timeout)
        return result

    def recv_bytes(self, timeout: float | None = None) -> bytes | None:
        """Wait for the reply and return raw bytes.

        Use when the Replier responded with :meth:`~Replier.send_bytes`.
        """
        result = poll_until(self._try_recv_bytes, timeout=timeout)
        return result

    def request(self, data, timeout: float | None = 5.0):
        """Convenience: send a request and immediately wait for the reply.

        Args:
            data:    Request payload.
            timeout: Total seconds to wait for a reply.

        Returns:
            Reply object, or ``None`` on timeout.

        Raises:
            SHMTimeoutError: If no reply arrives within *timeout*.

        Example::

            result = req.request({"cmd": "ping"}, timeout=1.0)
        """
        self.send(data)
        reply = self.recv(timeout=timeout)
        if reply is None:
            raise SHMTimeoutError(
                f"No reply from service '{self._name}' within "
                f"{timeout:.3f}s."
            )
        return reply

    def close(self) -> None:
        """Detach from the shared memory segments."""
        for attr in ("_req_shm", "_rep_shm"):
            shm = getattr(self, attr, None)
            if shm is not None:
                close_segment(shm, destroy=False)
                setattr(self, attr, None)
        logger.info("Requester('%s') closed", self._name)

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Requester":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _try_recv(self):
        result = read_message_spsc(self._rep_shm, self._rep_tail)
        if result is None:
            return None
        raw, new_tail = result
        self._rep_tail = new_tail
        return deserialize(raw, method=self._serialization)

    def _try_recv_bytes(self):
        result = read_message_spsc(self._rep_shm, self._rep_tail)
        if result is None:
            return None
        raw, new_tail = result
        self._rep_tail = new_tail
        return raw

    def _atexit_close(self) -> None:
        for attr in ("_req_shm", "_rep_shm"):
            if getattr(self, attr, None) is not None:
                self.close()
                break

    def __repr__(self) -> str:
        return f"Requester(name={self._name!r})"

"""
Serialization helpers for shm_comm.

Two backends are supported:

* ``pickle``   – built-in, handles any Python object (default).
* ``msgpack``  – faster for numeric-heavy data; requires the
                 ``msgpack`` package (``pip install msgpack``).

You can also pass raw :class:`bytes` or a :class:`bytearray` directly;
they are returned unchanged (zero-copy path).
"""

import pickle
import logging
from .exceptions import SHMSerializationError

logger = logging.getLogger("shmcomm.serialize")

# Try to import msgpack; silently degrade if not installed.
try:
    import msgpack as _msgpack
    _MSGPACK_AVAILABLE = True
except ImportError:
    _MSGPACK_AVAILABLE = False


def serialize(obj, method: str = "pickle") -> bytes:
    """Serialize *obj* to bytes using the chosen *method*.

    Args:
        obj:    Any Python object, or raw ``bytes``/``bytearray``.
        method: ``"pickle"`` (default) or ``"msgpack"``.

    Returns:
        Serialized payload as :class:`bytes`.

    Raises:
        SHMSerializationError: If serialization fails or msgpack is not
            installed when requested.

    Example::

        data = serialize({"cmd": "move", "pos": [1.0, 2.0, 3.0]})
    """
    # Raw bytes — pass through unchanged
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return bytes(obj)

    if method == "pickle":
        try:
            return pickle.dumps(obj, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            raise SHMSerializationError(
                f"pickle serialization failed: {exc}"
            ) from exc

    if method == "msgpack":
        if not _MSGPACK_AVAILABLE:
            raise SHMSerializationError(
                "msgpack is not installed. Run: pip install msgpack"
            )
        try:
            return _msgpack.packb(obj, use_bin_type=True)
        except Exception as exc:
            raise SHMSerializationError(
                f"msgpack serialization failed: {exc}"
            ) from exc

    raise SHMSerializationError(f"Unknown serialization method: {method!r}")


def deserialize(data: bytes, method: str = "pickle"):
    """Deserialize *data* back to a Python object.

    Args:
        data:   Raw bytes from the ring buffer.
        method: Must match the method used in :func:`serialize`.

    Returns:
        The original Python object.

    Raises:
        SHMSerializationError: If deserialization fails.

    Example::

        obj = deserialize(raw_bytes, method="pickle")
    """
    if method == "pickle":
        try:
            return pickle.loads(data)
        except Exception as exc:
            raise SHMSerializationError(
                f"pickle deserialization failed: {exc}"
            ) from exc

    if method == "msgpack":
        if not _MSGPACK_AVAILABLE:
            raise SHMSerializationError(
                "msgpack is not installed. Run: pip install msgpack"
            )
        try:
            return _msgpack.unpackb(data, raw=False)
        except Exception as exc:
            raise SHMSerializationError(
                f"msgpack deserialization failed: {exc}"
            ) from exc

    raise SHMSerializationError(f"Unknown serialization method: {method!r}")


def is_msgpack_available() -> bool:
    """Return ``True`` if the ``msgpack`` package is installed."""
    return _MSGPACK_AVAILABLE

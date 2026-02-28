"""
Custom exceptions for the shm_comm library.

All exceptions inherit from SHMError so callers can catch
everything with a single except clause if needed.
"""


class SHMError(Exception):
    """Base exception for all shm_comm errors."""


class SHMConnectionError(SHMError):
    """Raised when a shared memory segment cannot be created or attached.

    Example::

        try:
            sub = Subscriber("sensors")
        except SHMConnectionError as e:
            print(f"Cannot connect: {e}")
    """


class SHMTimeoutError(SHMError):
    """Raised when a blocking operation exceeds its timeout.

    Example::

        try:
            msg = sub.recv(timeout=1.0)
        except SHMTimeoutError:
            print("No message arrived in time")
    """


class SHMBufferFullError(SHMError):
    """Raised when a non-blocking send cannot write because the ring
    buffer is full and the caller passed ``block=False``.

    Example::

        try:
            pub.send(data, block=False)
        except SHMBufferFullError:
            print("Buffer full, dropping message")
    """


class SHMSerializationError(SHMError):
    """Raised when serialization or deserialization of a message fails.

    Example::

        try:
            pub.send(lambda x: x)     # lambdas can't be pickled
        except SHMSerializationError as e:
            print(f"Cannot serialize: {e}")
    """

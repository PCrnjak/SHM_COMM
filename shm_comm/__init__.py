"""
shm_comm — Shared Memory Communication Library
==============================================

A ZMQ/TCP-style IPC library using shared memory for ultra-low latency
communication between Python processes on the same machine.

Quick start::

    # Publish / Subscribe
    from shm_comm import Publisher, Subscriber

    pub = Publisher("my_channel")
    sub = Subscriber("my_channel")

    pub.send({"value": 42})
    msg = sub.recv(timeout=1.0)   # {"value": 42}

    # Request / Reply
    from shm_comm import Replier, Requester

    rep = Replier("my_service")
    req = Requester("my_service")

    req.send({"query": "ping"})
    request = rep.recv()
    rep.send({"pong": True})
    reply = req.recv()

    # Push / Pull (work queue)
    from shm_comm import Pusher, Puller

    push = Pusher("jobs")
    pull = Puller("jobs")

    push.send({"task": 1})
    job = pull.recv()
"""

__version__ = "1.0.0"
__author__ = "RAFT Robotics"

from .patterns.pubsub import Publisher, Subscriber
from .patterns.reqrep import Requester, Replier
from .patterns.pipeline import Pusher, Puller
from .exceptions import (
    SHMError,
    SHMConnectionError,
    SHMTimeoutError,
    SHMBufferFullError,
    SHMSerializationError,
)
from .utils import force_unlink, list_segments

__all__ = [
    # Patterns
    "Publisher",
    "Subscriber",
    "Requester",
    "Replier",
    "Pusher",
    "Puller",
    # Exceptions
    "SHMError",
    "SHMConnectionError",
    "SHMTimeoutError",
    "SHMBufferFullError",
    "SHMSerializationError",
    # Utilities
    "force_unlink",
    "list_segments",
]

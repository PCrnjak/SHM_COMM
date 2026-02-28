"""
command_executor.py — Receives commands via shared memory and processes them.

Mirrors the ZMQ pattern:
    - A background thread listens for incoming commands (like zmq_listener)
    - Commands are put into a Queue
    - The main loop reads from the queue and processes them
    - A "done" confirmation is sent back to the sender

Run this first, then run command_sender.py in another terminal:
    python examples/command_executor.py
"""

import threading
import time
from queue import Queue, Empty

SERVICE = "robot_commands"


def shm_listener(replier, command_queue: Queue, stop_event: threading.Event):
    """
    Background thread: waits for incoming commands and puts them in the queue.
    Mirrors zmq_listener() from the ZMQ version.
    """
    print("[Executor][Listener] Listening for commands …")
    while not stop_event.is_set():
        command = replier.recv(timeout=0.5)  # non-blocking-ish, returns None on timeout
        if command is not None:
            command_queue.put(command)


def main():
    from shm_comm import Replier

    command_queue = Queue()
    stop_event = threading.Event()

    print(f"[Executor] Starting command executor on service '{SERVICE}' …")
    print("[Executor] Waiting for commands. Press Ctrl+C to stop.\n")

    with Replier(SERVICE, num_slots=16, slot_size=4096) as replier:

        # Start background listener thread (mirrors threading.Thread(target=zmq_listener, ...))
        listener_thread = threading.Thread(
            target=shm_listener,
            args=(replier, command_queue, stop_event),
            daemon=True,
        )
        listener_thread.start()

        try:
            while True:
                # ================================================================
                # Main loop: check for new commands and send confirmations
                # Mirrors the ZMQ command_queue.get_nowait() block
                # ================================================================
                try:
                    command = command_queue.get_nowait()

                    # TODO:
                    #   If already executing a command and we get something here,
                    #   ignore it and report trash received.
                    #   If executing a command and we receive ESTOP, stop the program —
                    #   ESTOP has higher priority and overwrites the current command.

                    print(f"[Executor][Loop] Executing: {command!r}")

                    # --- process the command here ---
                    cmd_str = command if isinstance(command, str) else str(command)

                    if cmd_str.upper() == "ESTOP":
                        print("[Executor][Loop] *** EMERGENCY STOP received! ***")
                        replier.send("ESTOP_ACK")
                        break

                    # Simulate work (replace with your actual robot logic)
                    time.sleep(0.05)

                    # Send confirmation back (mirrors status_socket.send_string("done"))
                    try:
                        replier.send("done")
                        print(f"[Executor][Loop] Sent 'done' for: {command!r}")
                    except Exception as e:
                        print(f"[Executor][Loop] SHM overflow or no receiver: {e}")

                except Empty:
                    pass  # No command yet, keep loop going

                time.sleep(0.001)  # Small sleep to avoid busy-spinning the CPU

        except KeyboardInterrupt:
            print("\n[Executor] Shutting down …")
        finally:
            stop_event.set()
            listener_thread.join(timeout=2.0)
            print("[Executor] Done.")


if __name__ == "__main__":
    main()

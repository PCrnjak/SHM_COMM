"""
command_sender.py — Interactively sends typed commands via shared memory.

Mirrors the ZMQ sender side:
    - You type a command and press Enter
    - It's sent to command_executor.py
    - The executor processes it and sends back "done"
    - This script prints the confirmation

Run command_executor.py first, then this script:
    python examples/command_sender.py

Special commands:
    ESTOP   — emergency stop (executor will shut down)
    quit    — exit this sender
"""

import sys

SERVICE = "robot_commands"


def main():
    from shm_comm import Requester, SHMTimeoutError, SHMConnectionError

    print(f"[Sender] Connecting to service '{SERVICE}' …")
    print("[Sender] (Make sure command_executor.py is running first)\n")

    try:
        with Requester(SERVICE, timeout_connect=10.0) as req:
            print("[Sender] Connected! Type a command and press Enter.")
            print("[Sender] Type 'ESTOP' for emergency stop, 'quit' to exit.\n")

            while True:
                try:
                    command = input("Command> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n[Sender] Interrupted. Exiting.")
                    break

                if not command:
                    continue

                if command.lower() == "quit":
                    print("[Sender] Exiting.")
                    break

                # Send the command and wait for confirmation
                # Mirrors: status_socket.send_string("done") on the executor side
                print(f"[Sender] Sending: {command!r}")
                try:
                    reply = req.request(command, timeout=5.0)
                    print(f"[Sender] Got reply: {reply!r}\n")

                    if reply == "ESTOP_ACK":
                        print("[Sender] ESTOP acknowledged. Executor has stopped.")
                        break

                except SHMTimeoutError:
                    print("[Sender] Timeout — no reply from executor within 5 s\n")
                except SHMConnectionError as e:
                    print(f"[Sender] Connection error: {e}\n")
                    break

    except SHMConnectionError:
        print(
            "[Sender] ERROR: Could not connect to the executor.\n"
            "         Make sure command_executor.py is running first."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

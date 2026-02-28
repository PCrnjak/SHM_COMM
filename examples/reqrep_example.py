"""
reqrep_example.py — Request-reply service demonstration.

Start the server first:
    python examples/reqrep_example.py server

Then run the client:
    python examples/reqrep_example.py client
"""

import sys
import time

SERVICE = "example_arm_control"


def run_server():
    from shm_comm import Replier

    print(f"Arm control server listening on service '{SERVICE}' …")
    with Replier(SERVICE, num_slots=16, slot_size=2048) as rep:
        while True:
            request = rep.recv(timeout=5.0)
            if request is None:
                print("  (heartbeat — no request in 5 s)")
                continue

            print(f"  Request: {request}")

            # Simulate processing
            cmd = request.get("command", "unknown")
            if cmd == "get_status":
                response = {"status": "ok", "joints": [0.0, 90.0, -45.0, 0.0, 0.0, 0.0]}
            elif cmd == "move_joint":
                joint = request.get("joint", 0)
                angle = request.get("angle", 0.0)
                response = {"status": "ok", "moved": {"joint": joint, "angle": angle}}
            elif cmd == "stop":
                response = {"status": "ok", "message": "Emergency stop executed"}
            else:
                response = {"status": "error", "message": f"Unknown command: {cmd}"}

            rep.send(response)
            print(f"  Response: {response}")


def run_client():
    from shm_comm import Requester, SHMTimeoutError

    print(f"Connecting to service '{SERVICE}' …")
    with Requester(SERVICE, timeout_connect=10.0) as req:

        commands = [
            {"command": "get_status"},
            {"command": "move_joint", "joint": 2, "angle": 45.0},
            {"command": "move_joint", "joint": 4, "angle": -30.0},
            {"command": "stop"},
        ]

        for cmd in commands:
            print(f"\n  Sending: {cmd}")
            try:
                reply = req.request(cmd, timeout=3.0)
                print(f"  Got:     {reply}")
            except SHMTimeoutError as e:
                print(f"  TIMEOUT: {e}")
            time.sleep(0.2)


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("server", "client"):
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "server":
        run_server()
    else:
        run_client()

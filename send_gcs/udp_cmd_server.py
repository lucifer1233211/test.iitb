#!/usr/bin/env python3
"""
send_cmd.py — Send model commands to a Jetson running stream-mgr cmd-server.

Run this on your OTHER PC (not the Jetson).

Usage:
  python3 send_cmd.py --host 192.168.1.50 activate main detector
  python3 send_cmd.py --host 192.168.1.50 deactivate main detector
  python3 send_cmd.py --host 192.168.1.50 deactivate_all main
  python3 send_cmd.py --host 192.168.1.50 status
  python3 send_cmd.py --host 192.168.1.50 list_models main

Or use it as a library:
  from send_cmd import JetsonClient
  client = JetsonClient("192.168.1.50", 9200)
  client.activate("main", "detector")
  client.deactivate("main", "detector")
  print(client.status())
"""

import argparse
import json
import socket
import sys


class JetsonClient:
    def __init__(self, host: str, port: int = 9200, timeout: float = 5.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout

    def _send(self, payload: dict) -> dict:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        try:
            sock.sendto(json.dumps(payload).encode(), (self.host, self.port))
            raw, _ = sock.recvfrom(65535)
            return json.loads(raw.decode())
        except socket.timeout:
            return {"ok": False, "error": f"No response from {self.host}:{self.port} "
                                          f"(timeout {self.timeout}s)"}
        finally:
            sock.close()

    def activate(self, stream: str, key: str) -> dict:
        return self._send({"cmd": "activate", "stream": stream, "key": key})

    def deactivate(self, stream: str, key: str) -> dict:
        return self._send({"cmd": "deactivate", "stream": stream, "key": key})

    def deactivate_all(self, stream: str) -> dict:
        return self._send({"cmd": "deactivate_all", "stream": stream})

    def status(self) -> dict:
        return self._send({"cmd": "status"})

    def list_models(self, stream: str) -> dict:
        return self._send({"cmd": "list_models", "stream": stream})


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Send commands to Jetson stream-mgr over UDP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  activate      <stream> <key>   Start a model worker
  deactivate    <stream> <key>   Stop a model worker
  deactivate_all <stream>        Stop all models on a stream
  status                         Show all streams and model states
  list_models   <stream>         List models on a stream
        """
    )
    p.add_argument("--host",    required=True, help="Jetson IP address")
    p.add_argument("--port",    type=int, default=9200, help="UDP port (default 9200)")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("cmd",  help="Command name")
    p.add_argument("args", nargs="*", help="Command arguments")
    opts = p.parse_args()

    client = JetsonClient(opts.host, opts.port, opts.timeout)
    cmd    = opts.cmd
    args   = opts.args

    if cmd == "activate":
        if len(args) != 2:
            p.error("activate requires: <stream> <key>")
        result = client.activate(args[0], args[1])

    elif cmd == "deactivate":
        if len(args) != 2:
            p.error("deactivate requires: <stream> <key>")
        result = client.deactivate(args[0], args[1])

    elif cmd == "deactivate_all":
        if len(args) != 1:
            p.error("deactivate_all requires: <stream>")
        result = client.deactivate_all(args[0])

    elif cmd == "status":
        result = client.status()

    elif cmd == "list_models":
        if len(args) != 1:
            p.error("list_models requires: <stream>")
        result = client.list_models(args[0])

    else:
        p.error(f"Unknown command '{cmd}'. "
                "Use: activate, deactivate, deactivate_all, status, list_models")

    # Pretty print response
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
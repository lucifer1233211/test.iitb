#!/usr/bin/env python3
"""
udp_listener.py — Receives raw UDP packets containing JSON (or plain text)
and prints them to stdout (which stream_mgr tails via the logs command).

Your other PC sends with e.g.:
  echo '{"sensor": "imu", "ax": 0.1}' | nc -u <JETSON_IP> 9100
  or any custom sender that does socket.sendto(json_bytes, (jetson_ip, port))
"""

import argparse
import json
import signal
import socket
import sys
from datetime import datetime


def parse_args():
    p = argparse.ArgumentParser(description="UDP JSON listener")
    p.add_argument("--port",    type=int, default=9100,
                   help="UDP port to listen on (default: 9100)")
    p.add_argument("--host",    default="0.0.0.0",
                   help="Bind address (default: 0.0.0.0)")
    p.add_argument("--bufsize", type=int, default=65535,
                   help="Max UDP datagram size in bytes (default: 65535)")
    p.add_argument("--pretty",  action="store_true",
                   help="Pretty-print JSON with indentation")
    p.add_argument("--name",    default="udp",
                   help="Label used in log prefix")
    return p.parse_args()


def format_packet(raw: bytes, pretty: bool) -> str:
    """Try to parse as JSON; fall back to raw text."""
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
        if pretty:
            return json.dumps(data, indent=2, ensure_ascii=False)
        else:
            # Compact but validated JSON
            return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except json.JSONDecodeError:
        # Not JSON — just return the raw text
        return f"[raw] {text}"


def run():
    args = parse_args()
    name = args.name

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))

    # Graceful shutdown on SIGTERM
    shutdown = [False]

    def _sig(sig, _frame):
        print(f"\n[{name}] Received signal {sig}, shutting down…", flush=True)
        shutdown[0] = True
        sock.close()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    print(f"[{name}] Listening for UDP JSON on {args.host}:{args.port}", flush=True)
    print(f"[{name}] Pretty={args.pretty}  bufsize={args.bufsize}", flush=True)
    print(f"[{name}] {'─'*50}", flush=True)

    packet_count = 0
    while not shutdown[0]:
        try:
            data, addr = sock.recvfrom(args.bufsize)
        except OSError:
            # Socket closed by signal handler
            break

        packet_count += 1
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted = format_packet(data, args.pretty)

        print(f"[{ts}] [{addr[0]}:{addr[1]}] #{packet_count}", flush=True)
        print(formatted, flush=True)
        print(flush=True)  # blank line between packets

    print(f"[{name}] Listener stopped. Received {packet_count} packet(s).", flush=True)


if __name__ == "__main__":
    run()

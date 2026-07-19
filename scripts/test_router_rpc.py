#!/usr/bin/env python3
"""Quick arduino-router RPC probe (run on board with aware.service stopped)."""

from __future__ import annotations

import socket
import sys
import time

import msgpack


def blocking_call(method: str, timeout: float = 3.0) -> object:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect("/var/run/arduino-router.sock")
    req = [0, 1, method, []]
    s.sendall(msgpack.packb(req))
    data = s.recv(4096)
    s.close()
    if not data:
        return None
    return msgpack.unpackb(data, strict_map_key=False)


def main() -> None:
    methods = sys.argv[1:] or [
        "read_temp",
        "read_distance",
        "accel_x",
        "accel_y",
        "accel_z",
        "movement_intensity",
    ]
    for method in methods:
        t0 = time.time()
        try:
            resp = blocking_call(method)
            dt = time.time() - t0
            print(f"{method}: {resp!r} ({dt:.2f}s)")
        except Exception as exc:
            print(f"{method}: ERROR {exc!r}")


if __name__ == "__main__":
    main()

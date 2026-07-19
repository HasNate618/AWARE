#!/usr/bin/env python3
"""Probe arduino-router internal methods and STM32 serial link."""

from __future__ import annotations

import socket
import sys
import time

import msgpack


def rpc(method: str, args: list[object] | None = None, timeout: float = 3.0) -> object:
    args = [] if args is None else args
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect("/var/run/arduino-router.sock")
    req = [0, 1, method, args]
    s.sendall(msgpack.packb(req))
    data = s.recv(8192)
    s.close()
    if not data:
        return None
    return msgpack.unpackb(data, strict_map_key=False)


def main() -> None:
    probes = [
        ("mon/connected", []),
        ("hci/avail", []),
        ("$/serial/open", []),
        ("read_temp", []),
        ("bogus_method_xyz", []),
    ]
    if len(sys.argv) > 1:
        probes = [(m, []) for m in sys.argv[1:]]
    for method, args in probes:
        t0 = time.time()
        try:
            resp = rpc(method, args)
            dt = time.time() - t0
            print(f"{method}: {resp!r} ({dt:.2f}s)")
        except Exception as exc:
            print(f"{method}: ERROR {exc!r}")


if __name__ == "__main__":
    main()

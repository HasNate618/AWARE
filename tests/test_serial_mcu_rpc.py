from __future__ import annotations

import msgpack

from aware.app.mcu.serial_mcu import _pack_msg


def test_unix_socket_uses_raw_msgpack_not_length_prefix() -> None:
    """arduino-router Unix socket expects raw msgpack, not 4-byte length framing."""
    body = msgpack.packb([0, 1, "read_temp", []])
    assert body[0] == 0x94  # fixarray(4)
    assert _pack_msg([0, 1, "read_temp", []]) == body

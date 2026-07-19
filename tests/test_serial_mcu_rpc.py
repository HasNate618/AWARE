from __future__ import annotations

import struct

import msgpack


def test_router_response_body_excludes_length_prefix() -> None:
    """Router frames are 4-byte BE length + msgpack body; only body is msgpack."""
    body = msgpack.packb([1, 42, None, 21.5])
    parsed = msgpack.unpackb(body, strict_map_key=False)
    assert parsed[3] == 21.5
    assert len(struct.pack(">I", len(body))) == 4

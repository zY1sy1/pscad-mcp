"""Verify vendor relinking changes only the PE timestamp and checksum."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path


def _pe_payload(path: Path) -> tuple[bytes, dict[str, int]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("An owned regular executable is required")
    payload = path.read_bytes()
    if len(payload) < 64 or payload[:2] != b"MZ":
        raise ValueError("A valid PE executable is required")
    offset = struct.unpack_from("<I", payload, 60)[0]
    if offset < 64 or offset + 24 > len(payload):
        raise ValueError("Invalid PE header location")
    optional_size = struct.unpack_from("<H", payload, offset + 20)[0]
    if (
        payload[offset : offset + 4] != b"PE\0\0"
        or optional_size < 68
        or offset + 24 + optional_size > len(payload)
        or struct.unpack_from("<H", payload, offset + 24)[0] not in (0x10B, 0x20B)
    ):
        raise ValueError("Invalid PE optional header")
    return payload, {"link_timestamp": offset + 8, "checksum": offset + 24 + 64}


def verify_executable_relink(before_path: str | Path, after_path: str | Path) -> dict:
    """Reject changes anywhere except two defined PE metadata fields."""
    before, offsets = _pe_payload(Path(before_path))
    after, after_offsets = _pe_payload(Path(after_path))
    if offsets != after_offsets or len(before) != len(after):
        raise ValueError("Vendor relink changed executable structure")
    normalized = []
    for payload in (before, after):
        value = bytearray(payload)
        for offset in offsets.values():
            value[offset : offset + 4] = b"\0" * 4
        normalized.append(value)
    if normalized[0] != normalized[1]:
        raise ValueError("Vendor relink changed executable code or data")
    return {
        "policy": "pe_link_timestamp_checksum_only_v1",
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "code_and_data_unchanged": True,
        "bytes": len(after),
        "fields": {
            name: {
                "offset": offset,
                "before": struct.unpack_from("<I", before, offset)[0],
                "after": struct.unpack_from("<I", after, offset)[0],
            }
            for name, offset in offsets.items()
        },
    }

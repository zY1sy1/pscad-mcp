from __future__ import annotations

import struct

import pytest

from pscad_mcp.acceptance.executable_finalization import verify_executable_relink


@pytest.fixture
def executables(tmp_path):
    payload = bytearray(512)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 60, 128)
    payload[128:132] = b"PE\0\0"
    struct.pack_into("<H", payload, 148, 224)
    struct.pack_into("<H", payload, 152, 0x10B)
    paths = (tmp_path / "before.exe", tmp_path / "after.exe")
    for path in paths:
        path.write_bytes(payload)
    return paths


def test_relink_allows_only_defined_metadata(executables):
    before, after = executables
    payload = bytearray(after.read_bytes())
    struct.pack_into("<I", payload, 136, 100)
    struct.pack_into("<I", payload, 216, 123)
    after.write_bytes(payload)
    result = verify_executable_relink(before, after)
    assert result["code_and_data_unchanged"]
    assert result["fields"]["link_timestamp"]["after"] == 100
    assert result["before_sha256"] != result["after_sha256"]


@pytest.mark.parametrize("offset", [0, 60, 128, 148, 152, 220, 400, 511])
def test_relink_rejects_header_code_and_data_changes(executables, offset):
    before, after = executables
    payload = bytearray(after.read_bytes())
    payload[offset] ^= 1
    after.write_bytes(payload)
    with pytest.raises(ValueError):
        verify_executable_relink(before, after)


def test_relink_rejects_truncation(executables):
    before, after = executables
    after.write_bytes(after.read_bytes()[:-1])
    with pytest.raises(ValueError):
        verify_executable_relink(before, after)

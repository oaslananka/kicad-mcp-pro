"""Normalize ZIP DOS timestamps in MCPB bytes, without filesystem access.

The MCPB packer currently stamps entries with the wall clock time. We edit
only the four timestamp bytes in each local/central directory entry; source
payloads, compression, permissions and ZIP structure are preserved. Callers
must atomically replace their original archive only after this exits zero.
"""

from __future__ import annotations

import io
import struct
import sys
import zipfile

_FIXED_DOS_TIME_DATE = struct.pack("<HH", 0, 0x21)  # 1980-01-01 00:00:00
_MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_MAX_MEMBERS = 128
_LOCAL_SIGNATURE = b"PK\x03\x04"
_CENTRAL_SIGNATURE = b"PK\x01\x02"


def _check_entry(data: bytearray, offset: int, signature: bytes, length: int) -> None:
    if offset < 0 or data[offset : offset + 4] != signature or offset + length > len(data):
        raise ValueError("Invalid MCPB ZIP header")


def _validated_entries(original: bytes) -> tuple[list[zipfile.ZipInfo], int]:
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if not entries or len(entries) > _MAX_MEMBERS or len(set(names)) != len(names):
            raise ValueError("MCPB ZIP must contain at most 128 unique entries")
        if {"manifest.json", "icon.png"} - set(names):
            raise ValueError("MCPB ZIP is missing required files")
        if any(entry.flag_bits & 1 for entry in entries):
            raise ValueError("Encrypted MCPB entries are not supported")
        if sum(entry.file_size for entry in entries) > _MAX_BUNDLE_BYTES:
            raise ValueError("MCPB member data exceeds the size limit")
        if archive.testzip() is not None:
            raise ValueError("MCPB ZIP has invalid member CRC")
        return entries, archive.start_dir


def _member_name_bytes(data: bytearray, offset: int, size: int, entry: zipfile.ZipInfo) -> str:
    name_bytes = data[offset : offset + size]
    name_encoding = "utf-8" if entry.flag_bits & 0x800 else "cp437"
    return name_bytes.decode(name_encoding)


def _patch_local(data: bytearray, entry: zipfile.ZipInfo) -> None:
    offset = entry.header_offset
    _check_entry(data, offset, _LOCAL_SIGNATURE, 30)
    name_size = struct.unpack_from("<H", data, offset + 26)[0]
    if _member_name_bytes(data, offset + 30, name_size, entry) != entry.filename:
        raise ValueError("MCPB local ZIP entry name mismatch")
    data[offset + 10 : offset + 14] = _FIXED_DOS_TIME_DATE


def _patch_central(data: bytearray, offset: int, entry: zipfile.ZipInfo) -> int:
    _check_entry(data, offset, _CENTRAL_SIGNATURE, 46)
    name_size, extra_size, comment_size = struct.unpack_from("<HHH", data, offset + 28)
    if _member_name_bytes(data, offset + 46, name_size, entry) != entry.filename:
        raise ValueError("MCPB central ZIP entry name mismatch")
    data[offset + 12 : offset + 16] = _FIXED_DOS_TIME_DATE
    return int(offset + 46 + name_size + extra_size + comment_size)


def normalize_mcpb_timestamps(original: bytes) -> bytes:
    """Return verified timestamp-only normalized archive bytes, else raise."""
    if len(original) > _MAX_BUNDLE_BYTES:
        raise ValueError("MCPB bundle exceeds the normalization size limit")
    entries, offset = _validated_entries(original)
    data = bytearray(original)
    for entry in entries:
        _patch_local(data, entry)
    for entry in entries:
        offset = _patch_central(data, offset, entry)

    with zipfile.ZipFile(io.BytesIO(data)) as normalized:
        if normalized.testzip() is not None:
            raise ValueError("Normalized MCPB bundle failed ZIP validation")
        if any(entry.date_time != (1980, 1, 1, 0, 0, 0) for entry in normalized.infolist()):
            raise ValueError("Normalized MCPB has unexpected entry timestamp")
    return bytes(data)


def main() -> None:
    source = sys.stdin.buffer.read(_MAX_BUNDLE_BYTES + 1)
    result = normalize_mcpb_timestamps(source)
    sys.stdout.buffer.write(result)


if __name__ == "__main__":
    main()

"""Make MCPB archives reproducible by canonicalizing ZIP DOS timestamps only.

`mcpb pack` stamps source entries with pack time. Recompression would risk
changing file payloads/permissions/ZIP behavior; changing the four DOS-date
bytes in each local and central header preserves the original bundle intact.
Do this BEFORE checksums, attestations and publishing, in both producer paths.
"""

from __future__ import annotations

import argparse
import io
import os
import stat
import struct
import tempfile
import zipfile
from pathlib import Path

_FIXED_DOS_TIME_DATE = struct.pack("<HH", 0, 0x21)  # 1980-01-01 00:00:00
_MAX_BUNDLE_BYTES = 64 * 1024 * 1024
_LOCAL_SIGNATURE = b"PK\x03\x04"
_CENTRAL_SIGNATURE = b"PK\x01\x02"


def _check_entry(data: bytearray, offset: int, signature: bytes, length: int) -> None:
    if offset < 0 or data[offset : offset + 4] != signature or offset + length > len(data):
        raise ValueError("Invalid MCPB ZIP header")


def normalize_mcpb_timestamps(path: Path) -> None:
    """Patch only entry timestamps, fail closed on invalid ZIPs, write atomically."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("MCPB bundle must be a regular file")
    if path.stat().st_size > _MAX_BUNDLE_BYTES:
        raise ValueError("MCPB bundle exceeds the normalization size limit")

    original = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if not entries or len(set(names)) != len(names):
            raise ValueError("MCPB ZIP must contain unique entries")
        if {"manifest.json", "icon.png"} - set(names):
            raise ValueError("MCPB ZIP is missing required files")
        if any(entry.flag_bits & 1 for entry in entries):
            raise ValueError("Encrypted MCPB entries are not supported")
        if archive.testzip() is not None:
            raise ValueError("MCPB ZIP has invalid member CRC")
        central_offset = archive.start_dir

    data = bytearray(original)
    for entry in entries:
        local = entry.header_offset
        _check_entry(data, local, _LOCAL_SIGNATURE, 30)
        name_size = struct.unpack_from("<H", data, local + 26)[0]
        name_bytes = data[local + 30 : local + 30 + name_size]
        name_encoding = "utf-8" if entry.flag_bits & 0x800 else "cp437"
        if name_bytes.decode(name_encoding) != entry.filename:
            raise ValueError("MCPB local ZIP entry name mismatch")
        data[local + 10 : local + 14] = _FIXED_DOS_TIME_DATE

    offset = central_offset
    for entry in entries:
        _check_entry(data, offset, _CENTRAL_SIGNATURE, 46)
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", data, offset + 28)
        name_bytes = data[offset + 46 : offset + 46 + name_size]
        name_encoding = "utf-8" if entry.flag_bits & 0x800 else "cp437"
        if name_bytes.decode(name_encoding) != entry.filename:
            raise ValueError("MCPB central ZIP entry name mismatch")
        data[offset + 12 : offset + 16] = _FIXED_DOS_TIME_DATE
        offset += 46 + name_size + extra_size + comment_size

    if data == original:
        return
    with zipfile.ZipFile(io.BytesIO(data)) as normalized:
        if normalized.testzip() is not None or any(
            entry.date_time != (1980, 1, 1, 0, 0, 0) for entry in normalized.infolist()
        ):
            raise ValueError("Normalized MCPB bundle failed ZIP validation")

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
        os.chmod(temp_path, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path, help="Existing MCPB archive to normalize")
    args = parser.parse_args()
    normalize_mcpb_timestamps(args.artifact)


if __name__ == "__main__":
    main()

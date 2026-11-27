"""Conservative legacy folder-cache ACL decisions, independent of Win32 ABI."""

from __future__ import annotations

import pytest

USER = "S-1-5-21-123-456-789-1001"
OTHER = "S-1-5-21-123-456-789-1002"
SYSTEM = "S-1-5-18"
ADMINS = "S-1-5-32-544"
EVERYONE = "S-1-1-0"


@pytest.mark.parametrize(
    ("owner", "entries", "expected"),
    [
        (USER, [(0, 0, 0x1F01FF, USER), (0, 0, 0x1F01FF, SYSTEM)], True),
        (ADMINS, [(0, 0, 0x1F01FF, ADMINS), (0, 0, 0x120089, EVERYONE)], True),
        (USER, [(0, 0, 0xA0000000, OTHER)], True),
        (USER, [(0, 0, 0x40000000, EVERYONE)], False),
        (USER, [(0, 0, 0x00040000, OTHER)], False),
        (USER, [(0, 0, 0x40, OTHER)], False),
        (USER, [(0, 0, 0x00010000, OTHER)], False),
        (USER, [(0, 0, 0x10000000, EVERYONE)], False),
        (USER, [(1, 0, 0x1F01FF, EVERYONE), (0, 0, 0x1F01FF, USER)], True),
        (USER, [(0, 8, 0x1F01FF, EVERYONE)], True),
        (USER, [(5, 0, 0x120089, USER)], False),
        (OTHER, [(0, 0, 0x1F01FF, USER)], False),
        (USER, None, False),
    ],
)
def test_legacy_acl_never_trusts_other_writers(owner, entries, expected) -> None:
    from kicad_mcp.cloud_windows_legacy_acl import _owner_only_writers

    assert _owner_only_writers(USER, owner, entries) is expected

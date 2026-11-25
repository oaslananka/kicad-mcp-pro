"""Bounded saved-board footprint inventory; native source bytes remain authoritative."""

from __future__ import annotations

import hashlib
import math
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from ..file_formats import FOOTPRINT_LIST_READ_VERSIONS
from ..utils.sexpr import _unescape_sexpr_string

FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"
STRING_PATTERN = r'"((?:\\.|[^"\\])*)"'

# Only footprint identity and placement are projected. All other bytes are
# fingerprinted, not interpreted as topology or connectivity.
_BOARD_HEADER = re.compile(r"\s*\(kicad_pcb\s+\(version\s+(\d+)\)")
_BOARD_TOKENS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[()"]')
_CHILD_TAG = re.compile(r"\(([a-zA-Z_](?a:\w*))\b")
_MAX_INDEX_CHARS = 128 * 1024 * 1024
_MAX_INDEX_OBJECTS = 8192


def _board_child_tag(text: str, start: int) -> str:
    tag = _CHILD_TAG.match(text, start)
    if tag is None:
        raise ValueError("invalid native PCB child")
    return tag.group(1)


def _direct_board_children(text: str, start: int, end: int) -> Iterator[tuple[str, int, int]]:
    """Walk direct balanced children; quoted text cannot create a native object."""
    depth = 0
    child_start = start
    for token in _BOARD_TOKENS.finditer(text, start, end):
        value = token.group()
        if value == "(":
            if depth == 1:
                child_start = token.start()
            depth += 1
            continue
        if value == '"':
            raise ValueError("unclosed native PCB string")
        if value != ")":
            continue
        depth -= 1
        if depth == 1:
            yield _board_child_tag(text, child_start), child_start, token.end()
        elif depth == 0:
            break
    else:
        raise ValueError("unbalanced native PCB content")
    if text[token.end() : end].strip():
        raise ValueError("unexpected trailing native PCB content")


@dataclass(frozen=True, slots=True)
class FootprintListRecord:
    native_uuid: str
    reference: str
    value: str
    x_mm: float
    y_mm: float
    layer_name: str
    block_sha256: str
    nonplacement_sha256: str

    def as_entry(self) -> dict[str, Any]:
        return {
            "native_uuid": self.native_uuid,
            "value": self.value,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "layer_name": self.layer_name,
        }


@dataclass(frozen=True, slots=True)
class FootprintListRefresh:
    records: dict[str, FootprintListRecord]
    work_units: int
    board_context_sha256: str


def _native_list_fields(block: str) -> tuple[dict[str, str], dict[str, str], int]:
    spans: dict[str, tuple[int, int]] = {}
    properties: dict[str, str] = {}
    for tag, start, end in _direct_board_children(block, 0, len(block)):
        if tag in {"uuid", "at", "layer"}:
            if tag in spans:
                raise ValueError("duplicate native footprint field")
            spans[tag] = (start, end)
        elif tag == "property":
            prop = re.match(
                rf'\(property\s+"(Reference|Value)"\s+{STRING_PATTERN}', block[start:end]
            )
            if prop is not None:
                if prop.group(1) in properties:
                    raise ValueError("duplicate native footprint property")
                properties[prop.group(1)] = _unescape_sexpr_string(prop.group(2))
    fields = {tag: block[start:end] for tag, (start, end) in spans.items()}
    return fields, properties, spans.get("at", (0, 0))[0]


def _native_list_record(block: str, block_sha256: str) -> FootprintListRecord | None:
    fields, properties, at_start = _native_list_fields(block)
    if "uuid" not in fields:
        return None  # Older/synthetic files use the legacy uncached parser.
    stamp = re.fullmatch(rf"\(uuid\s+{STRING_PATTERN}\s*\)", fields["uuid"])
    at = re.fullmatch(
        rf"\(at\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})(?:\s+{FLOAT_PATTERN})?\s*\)",
        fields.get("at", ""),
    )
    layer = re.fullmatch(rf"\(layer\s+{STRING_PATTERN}\s*\)", fields.get("layer", ""))
    if stamp is None or at is None or layer is None or "Reference" not in properties:
        raise ValueError("incomplete native footprint identity or placement")
    parsed_uuid = UUID(stamp.group(1))
    identifier = str(parsed_uuid)
    if not parsed_uuid.int or identifier != stamp.group(1):
        raise ValueError("noncanonical native footprint UUID")
    x_mm, y_mm = float(at.group(1)), float(at.group(2))
    if not (math.isfinite(x_mm) and math.isfinite(y_mm)):
        raise ValueError("nonfinite native footprint position")
    return FootprintListRecord(
        identifier,
        properties["Reference"],
        properties.get("Value", ""),
        x_mm,
        y_mm,
        layer.group(1),
        block_sha256,
        _nonplacement_digest(block, at_start + at.start(1), at_start + at.end(2)),
    )


def _nonplacement_digest(block: str, start: int, end: int) -> str:
    # Preserve every byte except the two root placement coordinates, including
    # angle, nested pad positions, properties, and unknown children.
    digest = hashlib.sha256(block[:start].encode("utf-8"))
    digest.update(b"\0XY\0")
    digest.update(block[end:].encode("utf-8"))
    return digest.hexdigest()


class FileFootprintIndex:
    """One board's transient listing state; no native authority or disk writes.

    Reuse immutable rows only from exact matching decoded native footprint block text.
    Always read the current saved board before calling refresh; no TTL or
    filesystem timestamp is accepted as evidence of content equality.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scope: tuple[Path, str] | None = None
        self._digest: str | None = None
        self._context_digest = ""
        self._blocks: dict[str, FootprintListRecord] = {}

    def clear(self) -> None:
        with self._lock:
            self._scope = None
            self._digest = None
            self._context_digest = ""
            self._blocks = {}

    def refresh(self, path: Path, content: str) -> FootprintListRefresh | None:
        with self._lock:
            header = _BOARD_HEADER.match(content)
            if (
                header is None
                or header.group(1) not in FOOTPRINT_LIST_READ_VERSIONS
                or len(content) > _MAX_INDEX_CHARS
                or "\0" in content
            ):
                self.clear()
                return None
            scope = (path.absolute(), header.group(1))
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            previous = self._blocks if scope == self._scope else {}
            if scope == self._scope and digest == self._digest:
                return FootprintListRefresh(
                    {r.native_uuid: r for r in previous.values()}, 0, self._context_digest
                )
            # Clear before parsing: an exception or unsupported board cannot
            # leave an older snapshot available for later accidental reuse.
            self.clear()
            result = self._refresh_blocks(content, content.index("("), previous)
            if result is None:
                return None
            blocks, work_units, context_digest = result
            self._context_digest = context_digest
            self._scope, self._digest, self._blocks = scope, digest, blocks
            return FootprintListRefresh(
                {r.native_uuid: r for r in blocks.values()}, work_units, context_digest
            )

    @staticmethod
    def _refresh_blocks(
        content: str,
        start: int,
        previous: dict[str, FootprintListRecord],
    ) -> tuple[dict[str, FootprintListRecord], int, str] | None:
        blocks: dict[str, FootprintListRecord] = {}
        identities: set[str] = set()
        work_units = 0
        context = hashlib.sha256()
        cursor = 0
        for tag, begin, end in _direct_board_children(content, start, len(content)):
            if tag != "footprint":
                continue
            if len(blocks) >= _MAX_INDEX_OBJECTS:
                return None
            block = content[begin:end]
            digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
            record = previous.get(digest)
            if record is None:
                record = _native_list_record(block, digest)
                if record is None:
                    return None
                work_units += 1
            if record.native_uuid in identities:
                raise ValueError("duplicate native footprint identity")
            identities.add(record.native_uuid)
            blocks[digest] = record
            # Hash exact outside-footprint spans and ordered identities.
            context.update(content[cursor:begin].encode("utf-8"))
            context.update(b"\0FOOTPRINT:")
            context.update(record.native_uuid.encode("ascii"))
            context.update(b"\0")
            cursor = end
        context.update(content[cursor:].encode("utf-8"))
        return blocks, work_units, context.hexdigest()

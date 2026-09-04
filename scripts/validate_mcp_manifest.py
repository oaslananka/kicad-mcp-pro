#!/usr/bin/env python3
"""Validate the checked MCP registry manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import jsonschema

try:
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from runtime_path_safety import approved_runtime_path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT
DEFAULT_MANIFEST = ROOT / "server.json"
SERVER_SCHEMA = ROOT / "scripts" / "schemas" / "server.schema.json"
SUPPORTED_TRANSPORTS = frozenset({"stdio", "streamable-http", "sse"})
NAME_RE = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")
REGISTRY_META_KEY = "io.github.oaslananka/kicad-mcp-pro"
REPOSITORY = "https://github.com/oaslananka/kicad-mcp-pro"
WEBSITE = "https://oaslananka.github.io/kicad-mcp-pro"
VALID_SPDX_LICENSES = frozenset(
    {
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MPL-2.0",
        "GPL-3.0-only",
        "LGPL-3.0-only",
    }
)
SERVER_INFO_CAPABILITIES = [
    "fileBackedDrc",
    "fileBackedErc",
    "fileBackedExports",
    "livePcbRead",
    "livePcbWrite",
    "liveSchematicRead",
    "liveSchematicWrite",
    "chatgptConnectorCompatible",
    "cliExports",
]
REQUIRED_META_FIELDS = (
    "longDescription",
    "categories",
    "tags",
    "screenshots",
    "toolCatalog",
    "prerequisites",
    "supportedMcpProtocolVersions",
    "maintainer",
    "canonicalRepository",
    "license",
    "changelog",
    "releaseNotes",
    "serverInfo",
)


class ManifestValidationError(ValueError):
    """Raised when an MCP manifest fails validation."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = list(errors)


def _is_object(value: object) -> bool:
    return isinstance(value, Mapping)


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _url_errors(field: str, value: object) -> list[str]:
    url = _string(value)
    if not url:
        return [f"{field} must be a non-empty URL."]
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return [f"{field} must be an https URL."]
    return []


def _schema_path(path: Sequence[object]) -> str:
    if not path:
        return "<root>"
    return ".".join(str(part) for part in path)


def _official_schema_errors(manifest: Mapping[str, Any]) -> list[str]:
    try:
        schema = json.loads(SERVER_SCHEMA.read_text(encoding="utf-8"))
        validator_cls = jsonschema.validators.validator_for(schema)
        validator_cls.check_schema(schema)
        validator = validator_cls(schema, format_checker=jsonschema.FormatChecker())
        errors = sorted(validator.iter_errors(manifest), key=lambda error: list(error.path))
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        return [f"official MCP Registry schema could not be loaded: {exc}"]
    return [
        f"official MCP Registry schema {_schema_path(error.path)}: {error.message}"
        for error in errors
    ]


def _repository_url(manifest: Mapping[str, Any]) -> object:
    repository = manifest.get("repository")
    if isinstance(repository, str):
        return repository
    if _is_object(repository):
        return repository.get("url")
    return None


def _local_path_for_url(url: str) -> Path | None:
    github_blob = f"{REPOSITORY}/blob/main/"
    github_tree = f"{REPOSITORY}/tree/main/"
    if url.startswith(github_blob):
        return REPO_ROOT / unquote(url[len(github_blob) :])
    if url.startswith(github_tree):
        return REPO_ROOT / unquote(url[len(github_tree) :])
    if url.startswith(f"{WEBSITE}/"):
        return ROOT / "docs" / unquote(url[len(WEBSITE) + 1 :])
    return None


def _link_errors(field: str, value: object) -> list[str]:
    errors = _url_errors(field, value)
    if errors:
        return errors

    url = _string(value)
    local_path = _local_path_for_url(url)
    if local_path is None or local_path.exists():
        return []

    link_type = "repository" if url.startswith(REPOSITORY) else "website"
    rel = local_path.relative_to(REPO_ROOT) if local_path.is_relative_to(REPO_ROOT) else local_path
    return [f"{field} broken {link_type} link: {url} -> {rel} does not exist."]


def _list_of_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


def _transport_type(package: Mapping[str, Any]) -> str:
    transport = package.get("transport")
    if isinstance(transport, str):
        return transport
    if _is_object(transport):
        return _string(transport.get("type"))
    return ""


def _package_identity(package: Mapping[str, Any]) -> tuple[str, str]:
    registry = _string(package.get("registryType")) or _string(package.get("registry"))
    identifier = (
        _string(package.get("identifier"))
        or _string(package.get("name"))
        or _string(package.get("image"))
    )
    return registry, identifier


def _is_oci_registry(registry: str, package: Mapping[str, Any]) -> bool:
    return registry == "oci" or _string(package.get("registry")) == "container"


def _is_oci_identifier(identifier: str) -> bool:
    if not identifier or re.search(r"\s", identifier) or "://" in identifier:
        return False

    segments = identifier.split("/")
    if len(segments) < 2 or any(not segment for segment in segments):
        return False

    image_ref = "/".join(segments[1:])
    if "@" in image_ref:
        name, digest = image_ref.rsplit("@", 1)
        return (
            bool(name) and re.fullmatch(r"[A-Za-z0-9_+.-]+:[A-Za-z0-9=_+.-]+", digest) is not None
        )

    last_segment = segments[-1]
    if ":" not in last_segment:
        return False
    name, tag = last_segment.rsplit(":", 1)
    return bool(name and tag) and re.search(r"\s|/", tag) is None


def _has_command(manifest: Mapping[str, Any], packages: Sequence[Mapping[str, Any]]) -> bool:
    mcp = manifest.get("mcp")
    if _is_object(mcp) and _string(mcp.get("command")):
        return True
    return any(
        _string(package.get("command")) or _string(package.get("runtimeHint"))
        for package in packages
    )


def _registry_metadata_errors(manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []

    icons = manifest.get("icons")
    if not isinstance(icons, list) or not icons:
        errors.append("icons must include at least one public registry icon.")
    else:
        for index, icon in enumerate(icons):
            if not _is_object(icon):
                errors.append(f"icons[{index}] must be an object.")
                continue
            errors.extend(_link_errors(f"icons[{index}].src", icon.get("src")))

    meta_root = manifest.get("_meta")
    if not _is_object(meta_root) or not _is_object(meta_root.get(REGISTRY_META_KEY)):
        errors.append(
            f"_meta.{REGISTRY_META_KEY} is required for public registry listing metadata."
        )
        return errors

    meta = meta_root[REGISTRY_META_KEY]
    for field in REQUIRED_META_FIELDS:
        if field not in meta:
            errors.append(f"_meta.{REGISTRY_META_KEY}.{field} is required.")

    if not _string(meta.get("longDescription")):
        errors.append(f"_meta.{REGISTRY_META_KEY}.longDescription must be a non-empty string.")
    if not _list_of_strings(meta.get("categories")):
        errors.append(f"_meta.{REGISTRY_META_KEY}.categories must be a non-empty string list.")
    if not _list_of_strings(meta.get("tags")):
        errors.append(f"_meta.{REGISTRY_META_KEY}.tags must be a non-empty string list.")
    if not _list_of_strings(meta.get("prerequisites")):
        errors.append(f"_meta.{REGISTRY_META_KEY}.prerequisites must be a non-empty string list.")
    if not _list_of_strings(meta.get("supportedMcpProtocolVersions")):
        errors.append(
            f"_meta.{REGISTRY_META_KEY}.supportedMcpProtocolVersions must be a "
            "non-empty string list."
        )

    screenshots = meta.get("screenshots")
    if not isinstance(screenshots, list) or not screenshots:
        errors.append(f"_meta.{REGISTRY_META_KEY}.screenshots must be a non-empty list.")
    else:
        for index, screenshot in enumerate(screenshots):
            if not _is_object(screenshot):
                errors.append(f"_meta.{REGISTRY_META_KEY}.screenshots[{index}] must be an object.")
                continue
            if not _string(screenshot.get("caption")):
                errors.append(
                    f"_meta.{REGISTRY_META_KEY}.screenshots[{index}].caption "
                    "must be a non-empty string."
                )
            errors.extend(
                _link_errors(
                    f"_meta.{REGISTRY_META_KEY}.screenshots[{index}].src", screenshot.get("src")
                )
            )

    tool_catalog = meta.get("toolCatalog")
    if not _is_object(tool_catalog):
        errors.append(f"_meta.{REGISTRY_META_KEY}.toolCatalog must be an object.")
    else:
        if not _string(tool_catalog.get("summary")):
            errors.append(f"_meta.{REGISTRY_META_KEY}.toolCatalog.summary is required.")
        errors.extend(
            _link_errors(
                f"_meta.{REGISTRY_META_KEY}.toolCatalog.reference", tool_catalog.get("reference")
            )
        )

    maintainer = meta.get("maintainer")
    if not _is_object(maintainer):
        errors.append(f"_meta.{REGISTRY_META_KEY}.maintainer must be an object.")
    else:
        if not _string(maintainer.get("name")):
            errors.append(f"_meta.{REGISTRY_META_KEY}.maintainer.name is required.")
        errors.extend(
            _link_errors(f"_meta.{REGISTRY_META_KEY}.maintainer.url", maintainer.get("url"))
        )

    for field in ("canonicalRepository", "changelog", "releaseNotes"):
        errors.extend(_link_errors(f"_meta.{REGISTRY_META_KEY}.{field}", meta.get(field)))

    meta_license = _string(meta.get("license"))
    if meta_license != _string(manifest.get("license")):
        errors.append(f"_meta.{REGISTRY_META_KEY}.license must match license.")

    server_info = meta.get("serverInfo")
    if not _is_object(server_info):
        errors.append(f"_meta.{REGISTRY_META_KEY}.serverInfo must be an object.")
    else:
        if server_info.get("capabilities") != SERVER_INFO_CAPABILITIES:
            errors.append(
                f"_meta.{REGISTRY_META_KEY}.serverInfo.capabilities must match "
                "the server-info contract."
            )
        for field in ("schemaVersion", "mcpProtocolVersion", "toolSchemaVersion"):
            if not _string(server_info.get(field)):
                errors.append(f"_meta.{REGISTRY_META_KEY}.serverInfo.{field} is required.")

    return errors


def load_manifest(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load an MCP manifest from disk."""
    path = approved_runtime_path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestValidationError(["manifest root must be a JSON object."])
    return data


def validate_manifest(manifest: Mapping[str, Any]) -> list[str]:
    """Return validation errors for an MCP manifest."""
    errors: list[str] = []
    errors.extend(_official_schema_errors(manifest))

    for field in ("name", "description", "version", "license"):
        if not _string(manifest.get(field)):
            errors.append(f"{field} is required.")
    if _string(manifest.get("license")) and manifest.get("license") not in VALID_SPDX_LICENSES:
        errors.append("license must be a valid SPDX license identifier.")

    name = _string(manifest.get("name"))
    if name and NAME_RE.fullmatch(name) is None:
        errors.append("name must use reverse-DNS namespace format, for example io.github.org/name.")

    errors.extend(_url_errors("repository.url", _repository_url(manifest)))
    for url_field in ("homepage", "websiteUrl"):
        if url_field in manifest and manifest[url_field]:
            errors.extend(_url_errors(url_field, manifest[url_field]))

    raw_packages = manifest.get("packages")
    if not isinstance(raw_packages, list) or not raw_packages:
        errors.append("packages must be a non-empty list.")
        packages: list[Mapping[str, Any]] = []
    else:
        packages = []
        for index, item in enumerate(raw_packages):
            if not _is_object(item):
                errors.append(f"packages[{index}] must be an object.")
                continue
            packages.append(item)

    if packages and not _has_command(manifest, packages):
        errors.append("manifest must define mcp.command or a package command.")

    seen: set[tuple[str, str]] = set()
    for index, package in enumerate(packages):
        registry, identifier = _package_identity(package)
        if not registry:
            errors.append(f"packages[{index}] must define registryType or registry.")
        if not identifier:
            errors.append(f"packages[{index}] must define identifier, name, or image.")
        if not _is_oci_registry(registry, package) and not _string(package.get("version")):
            errors.append(f"packages[{index}] must define version.")
        if _is_oci_registry(registry, package) and _string(package.get("version")):
            errors.append(
                f"packages[{index}] OCI packages must not define version field; "
                "include version in identifier instead "
                "(e.g., 'ghcr.io/owner/image:1.0.0')."
            )
        if _is_oci_registry(registry, package):
            if "registryBaseUrl" in package:
                errors.append(
                    f"packages[{index}] must not define registryBaseUrl for OCI packages; "
                    "use a canonical registry/repository:tag identifier."
                )
            if identifier and not _is_oci_identifier(identifier):
                errors.append(
                    f"packages[{index}] OCI identifier must be registry/repository:tag "
                    "or registry/repository@algorithm:digest."
                )
        pair = (registry, identifier)
        if registry and identifier and pair in seen:
            errors.append(f"packages[{index}] duplicates package {registry}/{identifier}.")
        seen.add(pair)

        transport = _transport_type(package)
        if not transport:
            errors.append(f"packages[{index}] must define transport.type.")
        elif transport not in SUPPORTED_TRANSPORTS:
            errors.append(f"packages[{index}] uses unsupported transport {transport!r}.")

    mcp = manifest.get("mcp")
    if _is_object(mcp):
        transports = mcp.get("transports")
        if isinstance(transports, list):
            for transport in transports:
                if transport not in SUPPORTED_TRANSPORTS:
                    errors.append(f"mcp.transports contains unsupported transport {transport!r}.")

    errors.extend(_registry_metadata_errors(manifest))

    return errors


def validate_manifest_file(path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """Load and validate an MCP manifest, raising on failure."""
    manifest = load_manifest(path)
    errors = validate_manifest(manifest)
    if errors:
        raise ManifestValidationError(errors)
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        default=str(DEFAULT_MANIFEST),
        help="Path to mcp.json, default: repository root mcp.json.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.manifest)
    try:
        validate_manifest_file(path)
    except (OSError, json.JSONDecodeError, ManifestValidationError) as exc:
        print(f"MCP manifest validation failed for {path}:", file=sys.stderr)
        if isinstance(exc, ManifestValidationError):
            for error in exc.errors:
                print(f"- {error}", file=sys.stderr)
        else:
            print(f"- {exc}", file=sys.stderr)
        return 1
    print(f"MCP manifest validation passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

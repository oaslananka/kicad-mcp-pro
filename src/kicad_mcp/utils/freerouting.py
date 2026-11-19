"""Helpers for FreeRouting-based Specctra workflows."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

from ..config import get_config
from ..discovery import get_cli_capabilities
from ..errors import ManualStepRequiredError

logger = structlog.get_logger(__name__)


#: Settings passed on every run. Freerouting 2.x sends usage analytics and
#: telemetry by default and can start a GUI, a REST API server and an MCP
#: server; a headless batch route of a board file needs none of them.
FREEROUTING_PRIVACY_ARGS: tuple[str, ...] = (
    "--usage_and_diagnostic_data.disable_analytics=true",
    "--profile.allow_telemetry=false",
    "--gui.enabled=false",
    "--api_server.enabled=false",
    "--mcp_server.enabled=false",
)


@dataclass(frozen=True)
class FreeRoutingResult:
    """Normalized outcome of a FreeRouting autoroute run."""

    mode: str
    command: tuple[str, ...]
    input_dsn: Path
    output_ses: Path
    returncode: int
    stdout: str
    stderr: str
    routed_pct: float
    total_nets: int
    unrouted_nets: list[str]
    pass_count: int
    wall_seconds: float
    stdout_tail: str
    ses_path: Path
    excluded_nets: tuple[str, ...] = ()
    """Nets removed from the routed DSN copy (requested names found in the DSN)."""


def _sanitize_text(text: str) -> str:
    cfg = get_config()
    sanitized = text.replace(str(cfg.kicad_cli), "kicad-cli")
    if cfg.freerouting_jar is not None:
        sanitized = sanitized.replace(str(cfg.freerouting_jar), "<freerouting-jar>")
    if cfg.project_dir is not None:
        sanitized = sanitized.replace(str(cfg.project_dir), "<project>")
    return sanitized.strip()


def _common_parent(paths: list[Path]) -> Path:
    return Path(os.path.commonpath([str(path.resolve()) for path in paths]))


def _container_relpath(base: Path, target: Path) -> str:
    return target.resolve().relative_to(base.resolve()).as_posix()


def _tail(text: str, limit: int = 4096) -> str:
    return text[-limit:]


def _coerce_process_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


_DSN_TOKEN_RE = re.compile(r'"[^"]*"|[^\s()"]+')


def _dsn_block_end(text: str, start: int) -> int:
    """Return the index just past the parenthesis closing the DSN block at ``start``."""
    depth = 0
    in_string = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("Unbalanced Specctra DSN: no closing parenthesis found.")


def _dsn_children(text: str, start: int, end: int) -> list[tuple[str, int, int]]:
    """Return ``(tag, start, end)`` for the direct children of the block at ``start``."""
    children: list[tuple[str, int, int]] = []
    index = start + 1
    in_string = False
    while index < end - 1:
        char = text[index]
        if in_string:
            in_string = char != '"'
        elif char == '"':
            in_string = True
        elif char == "(":
            child_end = _dsn_block_end(text, index)
            tag = _DSN_TOKEN_RE.match(text, index + 1)
            children.append((tag.group(0) if tag else "", index, child_end))
            index = child_end
            continue
        index += 1
    return children


def _dsn_name(token: str) -> str:
    return token[1:-1] if len(token) >= 2 and token[0] == token[-1] == '"' else token


def _line_start(text: str, index: int) -> int:
    """Start of the line holding ``index`` when only whitespace precedes it there."""
    line_start = text.rfind("\n", 0, index)
    if text[line_start + 1 : index].strip():
        return index
    return line_start if line_start >= 0 else index


def _class_net_exclusion(
    text: str, start: int, end: int, wanted: set[str]
) -> tuple[tuple[int, int, str], set[str]] | None:
    """Remove selected net names from one Freerouting class membership list."""
    class_children = _dsn_children(text, start, end)
    members_end = class_children[0][1] if class_children else end - 1
    members_start = start + len("(class")
    span = text[members_start:members_end]
    tokens = _DSN_TOKEN_RE.findall(span)
    if len(tokens) < 2:
        return None
    kept = [tokens[0], *(tok for tok in tokens[1:] if _dsn_name(tok) not in wanted)]
    if len(kept) == len(tokens):
        return None
    found = {_dsn_name(tok) for tok in tokens[1:] if _dsn_name(tok) in wanted}
    leading = span[: len(span) - len(span.lstrip())]
    trailing = span[len(span.rstrip()) :]
    return (members_start, members_end, f"{leading}{' '.join(kept)}{trailing}"), found


def _remove_nets_from_dsn(text: str, nets: list[str]) -> tuple[str, tuple[str, ...]]:
    """Drop ``nets`` from a DSN network: their ``(net ...)`` blocks and class memberships.

    Their pads stay in the placement as obstacles without a net, so Freerouting
    leaves them unrouted. Returns the new text and the requested names found, in
    request order.
    """
    wanted = set(nets)
    network = re.search(r"\(network\b", text)
    if not wanted or network is None:
        return text, ()
    network_end = _dsn_block_end(text, network.start())
    edits: list[tuple[int, int, str]] = []
    found: set[str] = set()
    for tag, start, end in _dsn_children(text, network.start(), network_end):
        if tag == "net":
            name = _DSN_TOKEN_RE.match(text, start + len("(net"))
            name = name or _DSN_TOKEN_RE.search(text, start + len("(net"), end)
            if name is not None and _dsn_name(name.group(0)) in wanted:
                found.add(_dsn_name(name.group(0)))
                edits.append((_line_start(text, start), end, ""))
        elif tag == "class":
            class_edit = _class_net_exclusion(text, start, end, wanted)
            if class_edit is not None:
                edit, removed = class_edit
                edits.append(edit)
                found.update(removed)
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, tuple(name for name in dict.fromkeys(nets) if name in found)


def _count_dsn_nets(dsn_path: Path) -> int:
    try:
        content = dsn_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return len(re.findall(r"\(\s*net\b", content, flags=re.IGNORECASE))


def _parse_unrouted_nets(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(
        r"(?:unrouted|failed)\s+(?:net|connection)\s+['\"]?([A-Z0-9_.$:+/-]+)",
        text,
        flags=re.IGNORECASE,
    ):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def _parse_pass_count(text: str) -> int:
    passes = [
        int(match.group(1))
        for match in re.finditer(r"\bpass(?:es)?\s*+[:#]?\s*+(\d++)", text, flags=re.IGNORECASE)
    ]
    return max(passes) if passes else 0


def _parse_routed_pct(text: str, total_nets: int, unrouted_nets: list[str], ses_ok: bool) -> float:
    # Scan overlapping numeric starts and check the percent/label suffix literally.
    # Requiring the suffix within a regex permits super-linear backtracking.
    for number in re.finditer(r"(?=(?<!\d)(\d+(?:\.\d+)?))", text):
        cursor = number.start() + len(number.group(1))
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor >= len(text) or text[cursor] != "%":
            continue
        cursor += 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        suffix = text[cursor : cursor + 9].casefold()
        if suffix.startswith(("routed", "completed")):
            return round(float(number.group(1)), 2)
    if total_nets > 0 and unrouted_nets:
        return round(((total_nets - len(unrouted_nets)) / total_nets) * 100.0, 2)
    return 100.0 if ses_ok else 0.0


def _docker_available(executable: str) -> bool:
    return shutil.which(executable) is not None


class FreeRoutingRunner:
    """Run FreeRouting against project-provided Specctra files."""

    def __init__(
        self,
        *,
        docker_image: str | None = None,
        docker_executable: str | None = None,
        java_executable: str | None = None,
    ) -> None:
        cfg = get_config()
        self._docker_image = docker_image or cfg.freerouting_image
        self._docker_executable = docker_executable or cfg.docker_executable
        self._java_executable = java_executable or cfg.java_executable

    def _cli_export_dsn(self, kicad_cli: str | Path, pcb_path: Path, target: Path) -> bool:
        """Attempt the headless ``kicad-cli pcb export specctra`` command.

        Returns True only if a non-empty DSN file was produced. The capability probe
        gates the call, but the exact CLI build may still reject it, so failure is not
        fatal — the caller falls back to a manual-step path.
        """
        cli = str(kicad_cli)
        variants = [
            [cli, "pcb", "export", "specctra", "--output", str(target), str(pcb_path)],
            [cli, "pcb", "export", "specctra", "--input", str(pcb_path), "--output", str(target)],
        ]
        for cmd in variants:
            try:
                result = subprocess.run(  # noqa: S603
                    cmd, capture_output=True, text=True, timeout=120, check=False
                )
            except (OSError, subprocess.SubprocessError):
                continue
            if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
                return True
        return False

    def export_dsn(self, pcb_path: Path, dsn_path: Path) -> Path:
        """Export a Specctra DSN for FreeRouting, or raise a clear manual-step error.

        Tries an already-staged file, then a headless ``kicad-cli pcb export specctra``
        when the CLI advertises it, then known sidecar locations. If none succeed it
        raises ``ManualStepRequiredError`` describing the one-time GUI export rather than
        dead-ending.
        """
        cfg = get_config()
        target = cfg.resolve_within_project(dsn_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return target

        caps = get_cli_capabilities(cfg.kicad_cli)
        if caps.supports_specctra_export and self._cli_export_dsn(cfg.kicad_cli, pcb_path, target):
            return target

        candidates = [
            pcb_path.with_suffix(".dsn"),
            cfg.project_root / "routing" / f"{pcb_path.stem}.dsn",
            cfg.project_root / "output" / "routing" / f"{pcb_path.stem}.dsn",
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            if candidate.resolve() != target.resolve():
                shutil.copy2(candidate, target)
            return target

        raise ManualStepRequiredError(
            "Headless Specctra DSN export is not available from this KiCad CLI "
            f"({cfg.kicad_cli}). In KiCad's PCB Editor run File > Export > Specctra DSN and "
            f"save it to {target} (or next to {pcb_path.name}), then retry."
        )

    def _build_docker_command(
        self,
        *,
        dsn_path: Path,
        output: Path,
        drc_output: Path | None,
        max_passes: int,
        thread_count: int,
        ignore_arg: str,
    ) -> list[str]:
        mount_paths = [dsn_path, output]
        if drc_output is not None:
            mount_paths.append(drc_output)
        mount_root = _common_parent(mount_paths)
        dsn_arg = _container_relpath(mount_root, dsn_path)
        ses_arg = _container_relpath(mount_root, output)
        drc_arg = _container_relpath(mount_root, drc_output) if drc_output is not None else None
        command = [
            self._docker_executable,
            "run",
            "--rm",
            "-v",
            f"{mount_root}:/work",
            "-w",
            "/work",
            self._docker_image,
            "-de",
            dsn_arg,
            "-do",
            ses_arg,
            "-mp",
            str(max_passes),
            "-mt",
            str(thread_count),
            f"--router.max_passes={max_passes}",
            *FREEROUTING_PRIVACY_ARGS,
        ]
        if ignore_arg:
            command.extend(["-inc", ignore_arg])
        if drc_arg is not None:
            command.extend(["-drc", drc_arg])
        return command

    def _build_jar_command(
        self,
        *,
        jar_path: Path | None,
        dsn_path: Path,
        output: Path,
        drc_output: Path | None,
        max_passes: int,
        thread_count: int,
        ignore_arg: str,
    ) -> list[str]:
        if jar_path is None:
            raise RuntimeError(
                "FreeRouting JAR path is required when use_docker=False. "
                "Set KICAD_MCP_FREEROUTING_JAR or pass freerouting_jar_path."
            )
        command = [
            self._java_executable,
            "-jar",
            str(jar_path),
            "-de",
            str(dsn_path.resolve()),
            "-do",
            str(output),
            "-mp",
            str(max_passes),
            "-mt",
            str(thread_count),
            f"--router.max_passes={max_passes}",
            *FREEROUTING_PRIVACY_ARGS,
        ]
        if ignore_arg:
            command.extend(["-inc", ignore_arg])
        if drc_output is not None:
            command.extend(["-drc", str(drc_output)])
        return command

    def _resolve_command_and_mode(
        self,
        *,
        use_docker: bool,
        jar_path: Path | None,
        dsn_path: Path,
        output: Path,
        drc_output: Path | None,
        max_passes: int,
        thread_count: int,
        ignore_arg: str,
    ) -> tuple[str, list[str]]:
        selected_docker = use_docker
        if selected_docker and not _docker_available(self._docker_executable):
            if jar_path is None:
                raise RuntimeError(
                    "Docker was requested for FreeRouting but was not found, and no "
                    "FreeRouting JAR fallback is configured. Install Docker or set "
                    "KICAD_MCP_FREEROUTING_JAR."
                )
            selected_docker = False

        if selected_docker:
            return "docker", self._build_docker_command(
                dsn_path=dsn_path,
                output=output,
                drc_output=drc_output,
                max_passes=max_passes,
                thread_count=thread_count,
                ignore_arg=ignore_arg,
            )
        return "jar", self._build_jar_command(
            jar_path=jar_path,
            dsn_path=dsn_path,
            output=output,
            drc_output=drc_output,
            max_passes=max_passes,
            thread_count=thread_count,
            ignore_arg=ignore_arg,
        )

    def _execute_process(
        self,
        command: list[str],
        mode: str,
        dsn_path: Path,
        timeout: float,
    ) -> tuple[subprocess.CompletedProcess[str], float]:
        start_time = time.perf_counter()
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            missing = self._docker_executable if mode == "docker" else self._java_executable
            raise RuntimeError(
                f"{missing} was not found. Install the required runtime or switch "
                f"{'use_docker' if mode == 'docker' else 'to Docker mode'}."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            logger.warning(
                "freerouting_timeout",
                timeout_seconds=exc.timeout,
                dsn=dsn_path.name,
                stdout_tail=_tail(_sanitize_text(_coerce_process_output(exc.stdout))),
                stderr_tail=_tail(_sanitize_text(_coerce_process_output(exc.stderr))),
            )
            raise RuntimeError(
                f"FreeRouting timed out after {exc.timeout} seconds while "
                f"processing {dsn_path.name}."
            ) from exc
        wall_seconds = time.perf_counter() - start_time
        return result, wall_seconds

    def run_freerouting(
        self,
        dsn_path: Path,
        ses_path: Path,
        *,
        max_passes: int = 100,
        thread_count: int = 4,
        use_docker: bool = True,
        freerouting_jar_path: Path | None = None,
        net_classes_to_ignore: list[str] | None = None,
        exclude_nets: list[str] | None = None,
        drc_report_path: Path | None = None,
        timeout: float | None = None,
    ) -> FreeRoutingResult:
        """Run FreeRouting via Docker or a local JAR and return the normalized result."""
        cfg = get_config()
        if not dsn_path.exists():
            raise FileNotFoundError(f"Specctra DSN input was not found: {dsn_path}")

        output = ses_path.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        # -inc takes net *class* names; excluded nets leave a copy of the DSN instead.
        ignore_arg = ",".join(dict.fromkeys(net_classes_to_ignore or []))
        dsn_path, excluded = self._dsn_without_excluded_nets(dsn_path, exclude_nets or [])
        drc_output = drc_report_path.resolve() if drc_report_path is not None else None
        if drc_output is not None:
            drc_output.parent.mkdir(parents=True, exist_ok=True)

        jar_path = freerouting_jar_path or cfg.freerouting_jar
        mode, command = self._resolve_command_and_mode(
            use_docker=use_docker,
            jar_path=jar_path,
            dsn_path=dsn_path,
            output=output,
            drc_output=drc_output,
            max_passes=max_passes,
            thread_count=thread_count,
            ignore_arg=ignore_arg,
        )

        effective_timeout = timeout or cfg.freerouting_timeout_sec
        result, wall_seconds = self._execute_process(command, mode, dsn_path, effective_timeout)

        sanitized_stdout = _sanitize_text(result.stdout)
        sanitized_stderr = _sanitize_text(result.stderr)
        combined_output = f"{sanitized_stdout}\n{sanitized_stderr}"
        total_nets = _count_dsn_nets(dsn_path)
        unrouted_nets = _parse_unrouted_nets(combined_output)
        ses_ok = output.exists() and output.stat().st_size > 0
        routed_pct = _parse_routed_pct(combined_output, total_nets, unrouted_nets, ses_ok)

        return FreeRoutingResult(
            mode=mode,
            command=tuple(str(part) for part in command),
            input_dsn=dsn_path.resolve(),
            output_ses=output,
            returncode=result.returncode,
            stdout=sanitized_stdout,
            stderr=sanitized_stderr,
            routed_pct=routed_pct,
            total_nets=total_nets,
            unrouted_nets=unrouted_nets,
            pass_count=_parse_pass_count(combined_output),
            wall_seconds=round(wall_seconds, 3),
            stdout_tail=_tail(sanitized_stdout),
            ses_path=output,
            excluded_nets=excluded,
        )

    @staticmethod
    def _dsn_without_excluded_nets(
        dsn_path: Path, exclude_nets: list[str]
    ) -> tuple[Path, tuple[str, ...]]:
        """Return the DSN to route: a copy without ``exclude_nets``, or the original."""
        if not exclude_nets:
            return dsn_path, ()
        text = dsn_path.read_text(encoding="utf-8", errors="ignore")
        filtered, excluded = _remove_nets_from_dsn(text, exclude_nets)
        missing = [name for name in exclude_nets if name not in excluded]
        if missing:
            logger.warning("freerouting_excluded_nets_not_found", nets=missing)
        if not excluded:
            return dsn_path, ()
        routed = dsn_path.with_name(f"{dsn_path.stem}.excluded{dsn_path.suffix}")
        routed.write_text(filtered, encoding="utf-8")
        return routed, excluded

    def stage_ses(self, ses_path: Path) -> Path:
        """Copy the routed SES session into the project routing output and return it."""
        cfg = get_config()
        if not ses_path.exists():
            raise FileNotFoundError(f"Specctra SES session was not found: {ses_path}")
        staged = cfg.resolve_within_project(cfg.ensure_output_dir("routing") / ses_path.name)
        if staged.resolve() != ses_path.resolve():
            shutil.copy2(ses_path, staged)
        return staged

    def import_ses(self, pcb_path: Path, ses_path: Path) -> Path:
        """Stage the SES session, then raise the manual-import step it still requires.

        KiCad exposes no headless path to apply a routed Specctra SES session to a board,
        so this never silently "succeeds": it stages the file and raises
        ``ManualStepRequiredError`` describing the one-time GUI import. The staged path is
        in the message so the caller can surface exactly where the session is.
        """
        _ = pcb_path
        staged = self.stage_ses(ses_path)
        raise ManualStepRequiredError(
            f"The routed session is staged at {staged}, but KiCad has no headless Specctra "
            "SES import. Open the PCB in KiCad's PCB Editor and run File > Import > Specctra "
            "Session to apply the routing, then save the board."
        )

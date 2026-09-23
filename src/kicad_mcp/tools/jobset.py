"""KiCad CLI jobset export tools.

Wraps ``kicad-cli jobset`` subcommands for headless workflow automation.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .export_support import _ensure_output_dir, _run_cli, _run_cli_variants
from .metadata import headless_compatible


def register(mcp: FastMCP) -> None:
    """Register jobset (batch export) tools."""

    @headless_compatible
    def jobset_list_templates() -> str:
        """List available KiCad jobset templates.

        Runs ``kicad-cli jobset list`` and returns the JSON output parsed
        as a readable summary.  Jobset templates define pre-configured batch
        export workflows (Gerber + drill + PDF + IPC-2581, etc.).
        """
        cfg = get_config()
        code, stdout, stderr = _run_cli_variants(
            [
                ["jobset", "list", "--format", "json", str(cfg.kicad_cli.parent)],
                ["jobset", "list", "--format", "json"],
            ]
        )
        if code != 0:
            return f"Failed to list jobset templates: {stderr or 'unknown error'}"

        try:
            templates: Any = _json.loads(stdout)
        except _json.JSONDecodeError:
            return stdout or "Jobset templates listed (non-JSON output)."

        if isinstance(templates, list):
            if not templates:
                return "No jobset templates found."
            lines = [f"# Available Jobset Templates ({len(templates)})", ""]
            for tpl in templates:
                name = tpl.get("name", tpl.get("title", "?"))
                desc = tpl.get("description", tpl.get("desc", ""))
                lines.append(f"- **{name}**")
                if desc:
                    lines.append(f"  {desc}")
            return "\n".join(lines)

        return stdout or "Jobset templates listed."

    @headless_compatible
    def jobset_export(output_name: str = "") -> str:
        """Run a KiCad jobset to produce multiple export artifacts at once.

        A jobset is a JSON definition file that bundles several export steps
        (Gerber, drill, PDF, IPC-2581, ODB++, STEP, pick-and-place, BOM, …)
        into a single ``kicad-cli jobset export`` invocation.  The jobset
        definition is loaded from the project directory or from a template
        selected via ``jobset_list_templates``.

        Parameters
        ----------
        output_name : str
            Optional basename for the output archive (without extension).
            Defaults to the board basename.
        """
        cfg = get_config()
        if cfg.pcb_file is None:
            return "No PCB file configured. Call kicad_set_project() first."

        out_dir = _ensure_output_dir("jobset")
        board_stem = cfg.pcb_file.stem
        out_stem = Path(output_name.strip() or board_stem).name
        out_file = out_dir / f"{out_stem}.zip"

        code, _, stderr = _run_cli_variants(
            [
                [
                    "jobset",
                    "export",
                    "--output",
                    str(out_file),
                    str(cfg.pcb_file),
                ],
                [
                    "jobset",
                    "export",
                    "--input",
                    str(cfg.pcb_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Jobset export failed: {stderr or 'unknown error'}"

        existing = sorted(p for p in out_dir.iterdir() if p.is_file())
        lines = [f"Jobset export completed in {out_dir}:", ""]
        for p in existing:
            size = _format_size(p.stat().st_size)
            lines.append(f"- {p.name}  ({size})")
        return "\n".join(lines)

    @headless_compatible
    def jobset_run(
        project_file: str = "",
        jobset_file: str = "",
        output: str = "",
        stop_on_error: bool = True,
    ) -> str:
        """Run a KiCad jobset file against a project.

        Parameters
        ----------
        project_file : str
            Path to the KiCad project file (.kicad_pro). If omitted, the active project is used.
        jobset_file : str
            Path to the jobset file (.kicad_jobset). This parameter is required.
        output : str
            Jobset file output directory or file path.
        stop_on_error : bool
            Stop processing jobs sequentially on the first failure of a job.
        """
        cfg = get_config()
        if not jobset_file:
            return "Error: jobset_file parameter is required."

        proj_path = Path(project_file) if project_file else cfg.project_file
        if proj_path is None or not proj_path.exists():
            return "No KiCad project file configured or found. Call kicad_set_project() first."

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                jobset_path = resolve_under(cfg.project_dir, jobset_file)
            else:
                jobset_path = Path(jobset_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe jobset path: {exc}") from exc

        if not jobset_path.exists():
            return f"Jobset file not found: {jobset_file}"

        out_args = []
        if output:
            try:
                if cfg.project_dir is not None:
                    out_path = resolve_under(cfg.project_dir, output)
                else:
                    out_path = Path(output).expanduser().resolve()
                out_args = ["--output", str(out_path)]
            except Exception as exc:
                raise ValueError(f"Unsafe output path: {exc}") from exc

        cmd = ["jobset", "run"]
        if stop_on_error:
            cmd.append("--stop-on-error")
        cmd.extend(["--file", str(jobset_path)])
        cmd.extend(out_args)
        cmd.append(str(proj_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Jobset run failed: {stderr or stdout or 'unknown error'}"
        return f"Jobset executed successfully:\n{stdout or 'No output returned'}"

    @headless_compatible
    def jobset_validate(jobset_file: str = "") -> str:
        """Validate a KiCad jobset file's basic JSON structure.

        Parameters
        ----------
        jobset_file : str
            Path to the jobset file (.kicad_jobset) to validate.
        """
        cfg = get_config()
        if not jobset_file:
            return "Error: jobset_file parameter is required."

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                jobset_path = resolve_under(cfg.project_dir, jobset_file)
            else:
                jobset_path = Path(jobset_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe jobset path: {exc}") from exc

        if not jobset_path.exists():
            return f"Jobset file not found: {jobset_file}"

        try:
            with open(jobset_path, encoding="utf-8") as f:
                content = _json.load(f)
        except Exception as exc:
            return f"Validation failed: Invalid JSON format: {exc}"

        if "jobs" not in content:
            return "Validation failed: Missing required 'jobs' array key."

        jobs = content["jobs"]
        if not isinstance(jobs, list):
            return "Validation failed: 'jobs' must be a list."

        return f"Jobset file is valid. Found {len(jobs)} jobs defined."

    mcp.tool()(jobset_list_templates)
    mcp.tool()(jobset_export)
    mcp.tool()(jobset_run)
    mcp.tool()(jobset_validate)


def _format_size(bytes_count: int) -> str:
    """Format a byte count as a human-readable string."""
    count = float(bytes_count)
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024.0:
            return f"{count:.1f} {unit}"
        count /= 1024.0
    return f"{count:.1f} TB"

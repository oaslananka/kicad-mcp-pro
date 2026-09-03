from __future__ import annotations

import argparse
import json
from pathlib import Path

from kicad_mcp.evals.reference_agent_runner import (
    ReferenceAgentPhase,
    build_claude_command,
    build_mcp_config,
    load_phase_prompt,
    reviewed_mcp_tools,
    run_claude_session,
    write_agent_log,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated reference-board agent phase.")
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb", "manufacturing"), required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--scratch-dir", type=Path, required=True)
    parser.add_argument("--agent-log", type=Path, required=True)
    parser.add_argument("--checkout-dir", type=Path, required=True)
    parser.add_argument("--uv", type=Path, required=True)
    parser.add_argument("--kicad-cli", type=Path, required=True)
    parser.add_argument("--claude", default="claude")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--timeout-seconds", type=float, default=2700.0)
    parser.add_argument("--append-agent-log", action="store_true")
    return parser


def _require_scratch_outside_publication(checkout_dir: Path, scratch_dir: Path) -> None:
    publication_root = (checkout_dir / "docs/evidence/reference-boards").resolve()
    scratch = scratch_dir.resolve()
    if scratch == publication_root or scratch.is_relative_to(publication_root):
        raise SystemExit("scratch-dir must be outside docs/evidence/reference-boards")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _require_scratch_outside_publication(args.checkout_dir, args.scratch_dir)
    if args.agent_log.exists() and not args.append_agent_log:
        raise SystemExit("agent log already exists; use --append-agent-log to extend it")

    phase = ReferenceAgentPhase.for_name(args.phase)
    prompt = load_phase_prompt(args.prompt_file, phase)
    args.scratch_dir.mkdir(parents=True, exist_ok=True)
    settings_path = args.scratch_dir / f"{args.attempt_id}-{args.phase}-settings.json"
    mcp_config_path = args.scratch_dir / f"{args.attempt_id}-{args.phase}-mcp.json"
    settings_path.write_text("{}\n", encoding="utf-8")
    mcp_config = build_mcp_config(
        phase=phase,
        uv_executable=args.uv,
        checkout_dir=args.checkout_dir,
        project_dir=args.project_dir,
        kicad_cli=args.kicad_cli,
    )
    mcp_config_path.write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")
    command = build_claude_command(
        claude_executable=args.claude,
        model=args.model,
        settings_path=settings_path,
        mcp_config_path=mcp_config_path,
    )
    raw_stream_path = args.scratch_dir / f"{args.attempt_id}-{args.phase}-claude-stream.jsonl"
    summary = run_claude_session(
        command=command,
        prompt=prompt,
        raw_stream_path=raw_stream_path,
        attempt_id=args.attempt_id,
        cwd=args.checkout_dir,
        timeout_seconds=args.timeout_seconds,
        model=args.model,
        allowed_mcp_tools=reviewed_mcp_tools(phase),
    )
    write_agent_log(args.agent_log, summary, append=args.append_agent_log)
    print(
        json.dumps(
            {
                "attempt_id": args.attempt_id,
                "phase": args.phase,
                "successful": summary.successful,
                "primary_model": summary.primary_model,
                "auxiliary_models": list(summary.auxiliary_models),
                "provider": summary.provider,
                "permission_denials": summary.permission_denials,
                "terminal_reason": summary.terminal_reason,
                "event_count": len(summary.events),
            },
            sort_keys=True,
        )
    )
    return 0 if summary.successful else 1


if __name__ == "__main__":
    raise SystemExit(main())

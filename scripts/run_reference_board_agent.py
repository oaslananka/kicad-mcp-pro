import argparse
import json
from pathlib import Path

from kicad_mcp.evals.reference_agent_runner import (
    ReferenceAgentPhase,
    ReferenceAgentWorkspace,
    build_mcp_config,
    catalog_mcp_tools,
    discover_reference_kicad_cli,
    load_phase_prompt,
    reviewed_mcp_tools,
    run_claude_session,
    write_agent_log,
)

ROOT = Path(__file__).resolve().parents[1]
_SESSION_TIMEOUT_SECONDS = 2700.0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated reference-board agent phase.")
    parser.add_argument(
        "--board-id",
        choices=("esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc"),
        required=True,
    )
    parser.add_argument("--attempt-number", type=int, choices=range(1, 1000), required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb", "manufacturing"), required=True)
    parser.add_argument("--append-agent-log", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = ReferenceAgentWorkspace.for_reviewed_attempt(
        checkout_dir=ROOT, board_id=args.board_id, attempt_number=args.attempt_number
    )
    if workspace.agent_log_path.exists() and not args.append_agent_log:
        raise SystemExit("agent log already exists; use --append-agent-log to extend it")

    phase = ReferenceAgentPhase.for_name(args.phase)
    prompt = load_phase_prompt(workspace, phase)
    workspace.scratch_dir.mkdir(parents=True, exist_ok=True)
    workspace.project_dir.mkdir(parents=True, exist_ok=True)
    settings_path = workspace.phase_settings_path(phase)
    mcp_config_path = workspace.phase_mcp_config_path(phase)
    settings_path.write_text("{}\n", encoding="utf-8")
    mcp_config = build_mcp_config(
        phase=phase,
        workspace=workspace,
        kicad_cli=discover_reference_kicad_cli(),
    )
    mcp_config_path.write_text(json.dumps(mcp_config, indent=2) + "\n", encoding="utf-8")
    execution_tools = reviewed_mcp_tools(phase)
    catalog_tools = catalog_mcp_tools(phase)
    summary = run_claude_session(
        workspace=workspace,
        phase=phase,
        prompt=prompt,
        timeout_seconds=_SESSION_TIMEOUT_SECONDS,
        catalog_mcp_tools=catalog_tools,
        allowed_mcp_tools=execution_tools,
    )
    write_agent_log(workspace, summary, append=args.append_agent_log)
    print(
        json.dumps(
            {
                "attempt_id": workspace.attempt_id,
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

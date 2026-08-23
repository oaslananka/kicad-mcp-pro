"""Regression contract for the zero-cost DeepSeek OpenCode CLI candidate."""

from pathlib import Path

from kicad_mcp.evals.live_runner import load_configurations

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = ROOT / "evals/live/configurations.yaml"
RELEASE_GATE = ROOT / ".github/workflows/live-model-release-gate.yml"


def test_deepseek_cli_candidate_is_bounded_key_scoped_and_nonblocking() -> None:
    configurations = load_configurations(CONFIGURATIONS)
    configuration = configurations["opencode-cli-deepseek-v4-flash-free"]

    assert configuration.host == "opencode-zen-cli"
    assert configuration.model == "deepseek-v4-flash-free"
    assert configuration.required_env == ("OPENCODE_ZEN_API_KEY",)
    assert configuration.command == (
        "python",
        "scripts/opencode_cli_eval_adapter.py",
        "--model",
        "deepseek-v4-flash-free",
        "--opencode-bin",
        "opencode",
        "--timeout-seconds",
        "65",
    )
    assert configuration.limits.timeout_seconds == 70
    assert configuration.limits.max_retries == 2
    assert configuration.limits.max_total_cost_micros == 0

    release_gate = RELEASE_GATE.read_text(encoding="utf-8")
    assert "opencode-cli-deepseek-v4-flash-free" not in release_gate

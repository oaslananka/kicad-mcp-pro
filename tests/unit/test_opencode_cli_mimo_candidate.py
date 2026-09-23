"""Regression contract for the current zero-cost MiMo OpenCode CLI release candidate."""

from pathlib import Path

import yaml

from kicad_mcp.evals.live_runner import load_configurations

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = ROOT / "evals/live/configurations.yaml"
BASELINES = ROOT / "evals/live/baselines.yaml"
RELEASE_POLICY = ROOT / "evals/live/release-policy.yaml"
RELEASE_GATE = ROOT / ".github/workflows/live-model-release-gate.yml"


def test_mimo_cli_configuration_is_current_bounded_key_scoped_and_nonblocking() -> None:
    configurations = load_configurations(CONFIGURATIONS)
    configuration = configurations["opencode-cli-mimo-v2-5-free"]

    assert configuration.host == "opencode-zen-cli"
    assert configuration.model == "mimo-v2.5-free"
    assert configuration.required_env == ("OPENCODE_ZEN_API_KEY",)
    assert configuration.command == (
        "python",
        "scripts/opencode_cli_eval_adapter.py",
        "--model",
        "mimo-v2.5-free",
        "--opencode-bin",
        "opencode",
        "--timeout-seconds",
        "65",
    )
    assert configuration.limits.timeout_seconds == 70
    assert configuration.limits.max_retries == 4
    assert configuration.limits.max_total_cost_micros == 0
    assert "opencode-cli-deepseek-v4-flash-free" not in configurations

    release_gate = RELEASE_GATE.read_text(encoding="utf-8")
    assert "opencode-cli-mimo-v2-5-free" not in release_gate
    assert "opencode-cli-deepseek-v4-flash-free" not in release_gate

    release_policy = yaml.safe_load(RELEASE_POLICY.read_text(encoding="utf-8"))
    smoke_required = release_policy["smoke_configurations"]
    assert "opencode-cli-mimo-v2-5-free" not in smoke_required
    assert "opencode-cli-deepseek-v4-flash-free" not in smoke_required

    baselines = yaml.safe_load(BASELINES.read_text(encoding="utf-8"))
    full_required = baselines["required_configurations"]
    assert "opencode-cli-mimo-v2-5-free" not in full_required
    assert full_required == ["nvidia-nemotron-3-5-lightning-30b-a3b"]

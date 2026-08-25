"""Regression contract for the zero-cost Nemotron 3.5 Lightning OpenCode CLI candidate."""

from pathlib import Path

from kicad_mcp.evals.live_runner import load_configurations
from kicad_mcp.evals.opencode_zen_adapter import OPENCODE_ZEN_FREE_MODELS

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = ROOT / "evals/live/configurations.yaml"
RELEASE_GATE = ROOT / ".github/workflows/live-model-release-gate.yml"


def test_lightning_cli_candidate_is_reviewed_bounded_and_nonblocking() -> None:
    model = "nemotron-3.5-lightning-free"
    configuration_id = "opencode-cli-nemotron-3-5-lightning-free"

    assert model in OPENCODE_ZEN_FREE_MODELS

    configurations = load_configurations(CONFIGURATIONS)
    configuration = configurations[configuration_id]

    assert configuration.host == "opencode-zen-cli"
    assert configuration.model == model
    assert configuration.required_env == ("OPENCODE_ZEN_API_KEY",)
    assert configuration.command == (
        "python",
        "scripts/opencode_cli_eval_adapter.py",
        "--model",
        model,
        "--opencode-bin",
        "opencode",
        "--timeout-seconds",
        "120",
    )
    assert configuration.limits.timeout_seconds == 125
    assert configuration.limits.max_retries == 2
    assert configuration.limits.max_total_cost_micros == 0

    release_gate = RELEASE_GATE.read_text(encoding="utf-8")
    assert configuration_id not in release_gate

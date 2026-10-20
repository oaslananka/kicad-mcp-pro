"""Pytest configuration and Hypothesis profiles for advanced testing."""

from __future__ import annotations

import os
from pathlib import Path

from hypothesis import Phase, Verbosity, settings

# Register Hypothesis profiles
settings.register_profile(
    "smoke",
    max_examples=10,
    deadline=3000,
    verbosity=Verbosity.quiet,
)
settings.register_profile(
    "ci",
    max_examples=25,
    deadline=6000,
    phases=[Phase.explicit, Phase.reuse, Phase.generate],
    verbosity=Verbosity.normal,
)
settings.register_profile(
    "deep",
    max_examples=150,
    deadline=15000,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.shrink],
    verbosity=Verbosity.verbose,
)

# Load profile based on environment variable
hypothesis_profile = os.environ.get("HYPOTHESIS_PROFILE", "ci")
settings.load_profile(hypothesis_profile)

ADVANCED_ARTIFACTS_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "advanced-testing"

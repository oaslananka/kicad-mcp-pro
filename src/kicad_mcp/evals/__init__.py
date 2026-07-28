"""Evaluation harnesses for kicad-mcp.

Hosts the tool-selection eval and the golden-corpus eval:

- **Tool-selection eval:** a golden prompt suite plus a pure scorer that measures
  whether an agent calls the right tools (recall) and avoids forbidden ones.
- **Golden-corpus eval:** a project-level end-to-end benchmark that loads golden
  KiCad projects from ``evals/golden_corpus.yaml``, validates their structure,
  and (when KiCad is available) runs quality gates against answer keys.
"""

from .corpus import (
    CorpusEvalResult,
    CorpusEvalSummary,
    GoldenProject,
    aggregate_metrics,
    evaluate_corpus,
    evaluate_project,
    load_corpus,
)
from .tool_selection import (
    AgentRun,
    CaseResult,
    EvalCase,
    EvalThresholds,
    ThresholdOutcome,
    aggregate,
    aggregate_repeated,
    all_referenced_tools,
    evaluate_thresholds,
    load_cases,
    load_thresholds,
    run_eval,
    run_eval_repeated,
    score_case,
)

__all__ = [
    "AgentRun",
    "CaseResult",
    "CorpusEvalResult",
    "CorpusEvalSummary",
    "EvalCase",
    "EvalThresholds",
    "GoldenProject",
    "ThresholdOutcome",
    "aggregate",
    "aggregate_metrics",
    "aggregate_repeated",
    "all_referenced_tools",
    "evaluate_corpus",
    "evaluate_project",
    "evaluate_thresholds",
    "load_cases",
    "load_corpus",
    "load_thresholds",
    "run_eval",
    "run_eval_repeated",
    "score_case",
]

#!/usr/bin/env bash
# Execute the actual workflow wait body against deterministic, offline API fixtures.
set -euo pipefail

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
python3 - "$scratch/wait.sh" <<'PY'
import sys
from pathlib import Path

import yaml

workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text("utf-8"))
step = next(
    step for step in workflow["jobs"]["coverage"]["steps"]
    if step.get("id") == "native-windows-coverage"
)
Path(sys.argv[1]).write_text(step["run"], encoding="utf-8")
PY

# This is an offline test, not an authenticated GitHub operation.
unset GH_TOKEN GITHUB_TOKEN
export GITHUB_REPOSITORY=test/repo
export GITHUB_RUN_ID=45320850286 GITHUB_RUN_ATTEMPT=1
export COVERAGE_PRODUCER_HEAD=6a6a276f62c9c3d55be68c6b6f6ee558fb6d8b73
export COVERAGE_ARTIFACT="windows-python-coverage-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
export MOCK_ARTIFACT
MOCK_ARTIFACT="$(jq -cn --arg name "$COVERAGE_ARTIFACT" '{artifacts:[{id:14889028259,name:$name,expired:false}]}')"

gh() {
    if [[ "$1" != api ]]; then return 99; fi
    case "$2" in
        "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/artifacts?per_page=100")
            if [[ -f "$TRACE_FILE" ]]; then
                printf '%s' "$MOCK_ARTIFACT"
            else
                printf '%s' '{"artifacts":[]}'
            fi
            ;;
        "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/attempts/$GITHUB_RUN_ATTEMPT/jobs?per_page=100")
            if [[ "$MOCK_JOB_EXIT" != 0 ]]; then return 1; fi
            printf '%s' "$MOCK_JOBS"
            ;;
        *) return 99 ;;
    esac
}
sleep() { printf 'wait\n' >> "$TRACE_FILE"; }
export -f gh sleep

run_case() (
    local scenario="$1" upload="$2" api_exit="$3" expected="$4" waits="$5"
    export GITHUB_OUTPUT="$scratch/$scenario.output" TRACE_FILE="$scratch/$scenario.trace"
    export MOCK_JOB_EXIT="$api_exit" MOCK_JOBS
    MOCK_JOBS="$(jq -cn --arg upload "$upload" --arg head "$COVERAGE_PRODUCER_HEAD" \
        --argjson run "$GITHUB_RUN_ID" --argjson attempt "$GITHUB_RUN_ATTEMPT" \
        '{total_count:1,jobs:[{name:"mcp-server (windows-2025)",run_id:$run,run_attempt:$attempt,head_sha:$head,status:"completed",conclusion:"failure",steps:[{name:"Upload exact-run native Windows coverage",status:"completed",conclusion:$upload}]}]}')"
    : > "$GITHUB_OUTPUT"
    local status=0
    bash "$scratch/wait.sh" || status=$?
    test "$status" = "$expected"
    if [[ "$waits" == yes ]]; then
        test "$(cat "$TRACE_FILE")" = wait
        test "$(wc -l < "$TRACE_FILE")" -eq 1
        test "$(cat "$GITHUB_OUTPUT")" = artifact_id=14889028259
    else
        test ! -e "$TRACE_FILE"
        test ! -s "$GITHUB_OUTPUT"
    fi
    printf 'PASS: %s\n' "$scenario"
)

run_case impossible-upload skipped 0 1 no
run_case visibility-delay success 0 0 yes
run_case api-failure success 1 1 no

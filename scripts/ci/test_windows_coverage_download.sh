#!/usr/bin/env bash
# Exercise the actual workflow download command offline; never contact GitHub.
set -euo pipefail
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
python3 - "$scratch" <<'PY'
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import yaml

root = Path(sys.argv[1])
workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text("utf-8"))
step = next(s for s in workflow["jobs"]["coverage"]["steps"]
            if s.get("name") == "Download native Windows coverage for this run")
(root / "step.sh").write_text(step["run"], encoding="utf-8")
with zipfile.ZipFile(root / "archive.zip", "w") as archive:
    archive.writestr("windows-coverage.json", '{"files":{"src/kicad_mcp/server.py":{}}}')
    archive.writestr("windows-coverage-manifest.json", "{}")
blob = (root / "archive.zip").read_bytes()
metadata = {
    "id": 14892789567, "name": "windows-python-coverage-45333003080-1",
    "expired": False, "size_in_bytes": len(blob),
    "digest": "sha256:" + hashlib.sha256(blob).hexdigest(),
    "workflow_run": {"id": 45333003080, "repository_id": 1255527274,
                     "head_sha": "958110d761c7f35b880ef45d9d8bc9b7079662a9"},
}
for name, change in (
    ("valid", {}), ("expired", {"expired": True}), ("foreign", {"id": 1}),
    ("digest", {"digest": "sha256:" + "0" * 64}),
):
    (root / f"{name}.json").write_text(json.dumps(metadata | change), encoding="utf-8")
PY
export FIXTURE_ROOT="$scratch"
export GITHUB_REPOSITORY=test/repo GITHUB_REPOSITORY_ID=1255527274
export GITHUB_RUN_ID=45333003080 GITHUB_RUN_ATTEMPT=1
export COVERAGE_PRODUCER_HEAD=958110d761c7f35b880ef45d9d8bc9b7079662a9
export COVERAGE_ARTIFACT_ID=14892789567
unset GH_TOKEN GITHUB_TOKEN

timeout() {
    local kill_after="$1" deadline="$2" executable="$3" command="$4" host_flag="$5" host="$6" endpoint="$7"
    [[ "$kill_after" == --kill-after=5s && "$deadline" == 30s ]] || return 99
    [[ "$executable" == gh && "$command" == api && "$host_flag" == --hostname && "$host" == github.com ]] || return 99
    local kind
    case "$endpoint" in
        "repos/$GITHUB_REPOSITORY/actions/artifacts/$COVERAGE_ARTIFACT_ID") kind=metadata ;;
        "repos/$GITHUB_REPOSITORY/actions/artifacts/$COVERAGE_ARTIFACT_ID/zip") kind=zip ;;
        *) return 99 ;;
    esac
    local count=0
    if [[ -f "$TRACE_DIR/$kind" ]]; then read -r count < "$TRACE_DIR/$kind"; fi
    printf '%s\n' "$((count+1))" > "$TRACE_DIR/$kind"
    case "$MOCK_MODE:$kind:$count" in
        delayed:metadata:0|delayed:zip:0|exhausted:zip:*)
            printf 'gh: Not Found (HTTP 404)\n' >&2
            return 1 ;;
        permanent:metadata:*) printf 'gh: Forbidden (HTTP 403)\n' >&2; return 1 ;;
        timeout:zip:0) return 124 ;;
        busy:metadata:0) printf 'gh: Too Many Requests (HTTP 429)\n' >&2; return 1 ;;
        busy:zip:0) printf 'gh: Bad Gateway (HTTP 502)\n' >&2; return 1 ;;
        gone:zip:*) printf 'gh: Gone (HTTP 410)\n' >&2; return 1 ;;
        success:*:*|delayed:*:*|timeout:*:*|busy:*:*|gone:metadata:*|digest:*:*|exhausted:metadata:*|expired:metadata:*|foreign:metadata:*) : ;;
        *) return 99 ;;
    esac
    if [[ "$kind" == zip ]]; then
        cat "$FIXTURE_ROOT/archive.zip"
    else
        case "$MOCK_MODE" in
            expired|foreign|digest) cat "$FIXTURE_ROOT/$MOCK_MODE.json" ;;
            *) cat "$FIXTURE_ROOT/valid.json" ;;
        esac
    fi
}
sleep() { printf 'wait\n' >> "$TRACE_DIR/sleeps"; }
export -f timeout sleep

run_case() (
    local scenario="$1" expected="$2" metadata_calls="$3" zip_calls="$4" waits="$5"
    local project="$scratch/$scenario/project"
    mkdir -p "$project/scripts/ci" "$scratch/$scenario/trace"
    cp scripts/ci/download_windows_coverage.sh "$project/scripts/ci/"
    cp scripts/verify_windows_coverage_archive.py "$project/scripts/"
    export TRACE_DIR="$scratch/$scenario/trace" MOCK_MODE="$scenario"
    cd "$project"
    local status=0
    bash "$FIXTURE_ROOT/step.sh" || status=$?
    [[ "$status" == "$expected" ]]
    [[ "$(cat "$TRACE_DIR/metadata")" == "$metadata_calls" ]]
    if [[ "$zip_calls" == 0 ]]; then
        [[ ! -e "$TRACE_DIR/zip" ]]
    else
        [[ "$(cat "$TRACE_DIR/zip")" == "$zip_calls" ]]
    fi
    if [[ "$waits" == 0 ]]; then
        [[ ! -e "$TRACE_DIR/sleeps" ]]
    else
        [[ "$(wc -l < "$TRACE_DIR/sleeps")" -eq "$waits" ]]
    fi
    if [[ "$expected" == 0 ]]; then
        [[ -s windows-coverage.json && -s windows-coverage-manifest.json ]]
    else
        [[ ! -e windows-coverage.json && ! -e windows-coverage-manifest.json ]]
    fi
    printf 'PASS: %s\n' "$scenario"
)
run_case success 0 1 1 0
run_case delayed 0 2 2 2
run_case timeout 0 1 2 1
run_case busy 0 2 2 2
run_case gone 1 1 1 0
run_case permanent 1 1 0 0
run_case expired 1 1 0 0
run_case foreign 1 1 0 0
run_case digest 1 1 1 0
run_case exhausted 1 1 4 3
run_case unknown 1 1 0 0

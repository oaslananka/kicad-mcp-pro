#!/usr/bin/env bash
# Download only the ID selected by the exact-run artifact wait step.
# Retry bounded REST visibility failures, never failed evidence validation.
set -euo pipefail

if [[ ! "$GITHUB_REPOSITORY" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ||
      ! "$COVERAGE_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]; then
    echo "::error::Invalid coverage artifact request identity."
    exit 1
fi
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
route="repos/$GITHUB_REPOSITORY/actions/artifacts/$COVERAGE_ARTIFACT_ID"

fetch_exact() {
    local endpoint="$1" destination="$2" limit="$3"
    local attempt status
    for attempt in 1 2 3 4; do
        status=0
        # Bound disk writes and request duration; do not log API response bodies.
        (ulimit -f "$limit" || exit 1; timeout --kill-after=5s 30s gh api --hostname github.com "$endpoint") \
            > "$destination" 2> "$scratch/error" || status=$?
        if [[ "$status" == 0 ]]; then
            return 0
        fi
        if [[ "$status" != 124 ]] &&
           ! grep -Eq '^gh: .+ \(HTTP (404|429|5[0-9]{2})\)$' "$scratch/error"; then
            echo "::error::Permanent or unclassified native coverage download failure."
            return 1
        fi
        if [[ "$attempt" == 4 ]]; then
            echo "::error::Native coverage download visibility retry limit reached."
            return 1
        fi
        echo "::notice::Native coverage temporarily unavailable; retrying exact artifact ID."
        sleep 5
    done
}

identity=(
    --artifact-id "$COVERAGE_ARTIFACT_ID"
    --run-id "$GITHUB_RUN_ID"
    --attempt "$GITHUB_RUN_ATTEMPT"
    --head "$COVERAGE_PRODUCER_HEAD"
    --repository-id "$GITHUB_REPOSITORY_ID"
    --metadata "$scratch/metadata.json"
)
fetch_exact "$route" "$scratch/metadata.json" 1024
python3 scripts/verify_windows_coverage_archive.py "${identity[@]}" --metadata-only
fetch_exact "$route/zip" "$scratch/archive.zip" 21000
python3 scripts/verify_windows_coverage_archive.py "${identity[@]}" --archive "$scratch/archive.zip"

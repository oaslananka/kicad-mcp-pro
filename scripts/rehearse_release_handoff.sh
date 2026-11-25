#!/usr/bin/env bash
# Scoped transport rehearsal only. No production publisher, release or registry mutation.
set -euo pipefail

readonly repo='oaslananka/kicad-mcp-pro'
readonly root="repos/$repo/actions"
readonly api_version='X-GitHub-Api-Version: 2026-03-10'
readonly owner_path='.github/workflows/release-handoff-rehearsal.yml'
readonly owner_actor_id=285490571
readonly worker_actor_id=41898282
readonly worker_path='.github/workflows/release-handoff-worker.yml'

fail() { printf 'handoff rehearsal: %s\n' "$*" >&2; exit 1; }
api() { gh api -H "$api_version" "$@"; }
positive_id() { local value="$1"; [[ "$value" =~ ^[1-9][0-9]{0,14}$ ]]; }

# All supplied input stays data. Require the exact canonical main checkout.
[[ "$GITHUB_REPOSITORY" == "$repo" && "$GITHUB_REF" == refs/heads/main ]] || fail 'wrong repository or ref'
[[ "$GITHUB_EVENT_NAME" == workflow_dispatch && "$GITHUB_SHA" =~ ^[a-f0-9]{40}$ ]] || fail 'wrong event or SHA'
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]] || fail 'wrong checkout'
positive_id "$GITHUB_RUN_ID" || fail 'invalid run ID'
positive_id "$GITHUB_RUN_ATTEMPT" || fail 'invalid run attempt'
digest="$(sha256sum server.json | cut -d' ' -f1)"

verify_run() {
    local id="$1" attempt="$2" path="$3" actor="$4" status="$5" actor_id="$6"
    api "$root/runs/$id" | jq -e --arg repo "$repo" --arg sha "$GITHUB_SHA" \
        --arg id "$id" --arg attempt "$attempt" --arg path "$path" \
        --arg actor "$actor" --arg status "$status" --arg actor_id "$actor_id" '
        .id == ($id|tonumber) and .run_attempt == ($attempt|tonumber) and
        .repository.full_name == $repo and .head_repository.full_name == $repo and
        (.repository.id | type == "number" and . > 0) and
        .repository.id == .head_repository.id and
        (.path == $path or .path == ($path + "@main")) and
        .event == "workflow_dispatch" and .head_branch == "main" and .head_sha == $sha and
        .actor.login == $actor and .triggering_actor.login == $actor and
        .actor.id == ($actor_id|tonumber) and .triggering_actor.id == ($actor_id|tonumber) and
        .status == $status and
        (if $status == "completed" then .conclusion == "success" else .conclusion == null end)
    ' >/dev/null
}

receipt() {
    local worker_id="$1"
    jq -n --arg repository "$repo" --arg source "$GITHUB_SHA" --arg digest "$digest" \
        --arg owner "$OWNER_RUN_ID" --arg attempt "$OWNER_ATTEMPT" --arg worker "$worker_id" '
        {repository: $repository, sourceCommit: $source, manifestSha256: $digest,
         ownerRunId: ($owner|tonumber), ownerRunAttempt: ($attempt|tonumber),
         workerRunId: ($worker|tonumber), workerRunAttempt: 1,
         rehearsal: true, publicationAuthorized: false, exclusiveWriterVerified: false}'
}

case "$1" in
    worker)
        [[ "$GITHUB_ACTOR" == 'github-actions[bot]' && "$GITHUB_TRIGGERING_ACTOR" == 'github-actions[bot]' && "$GITHUB_ACTOR_ID" == "$worker_actor_id" ]] || fail 'not dispatched by Actions'
        [[ "$GITHUB_RUN_ATTEMPT" == 1 ]] || fail 'worker reruns are not accepted'
        # No dispatch parameters. Resolve the one active serialized rehearsal
        # owner for this exact main commit; ambiguity denies the handoff.
        owner="$(api "$root/workflows/release-handoff-rehearsal.yml/runs?branch=main&event=workflow_dispatch&status=in_progress&head_sha=$GITHUB_SHA&per_page=100" |
            jq -ce 'select(.total_count == 1 and (.workflow_runs|length) == 1) | .workflow_runs[0]')"
        OWNER_RUN_ID="$(jq -er '.id|tostring' <<<"$owner")"
        OWNER_ATTEMPT="$(jq -er '.run_attempt|tostring' <<<"$owner")"
        positive_id "$OWNER_RUN_ID" || fail 'invalid owner run ID'
        positive_id "$OWNER_ATTEMPT" || fail 'invalid owner attempt'
        [[ "$OWNER_RUN_ID" != "$GITHUB_RUN_ID" ]] || fail 'self handoff'
        verify_run "$OWNER_RUN_ID" "$OWNER_ATTEMPT" "$owner_path" oaslananka in_progress "$owner_actor_id"
        verify_run "$GITHUB_RUN_ID" 1 "$worker_path" 'github-actions[bot]' in_progress "$worker_actor_id"
        receipt "$GITHUB_RUN_ID" > handoff-receipt.json
        ;;
    owner)
        [[ "$GITHUB_ACTOR" == oaslananka && "$GITHUB_TRIGGERING_ACTOR" == oaslananka && "$GITHUB_ACTOR_ID" == "$owner_actor_id" ]] || fail 'owner dispatch required'
        OWNER_RUN_ID="$GITHUB_RUN_ID"
        OWNER_ATTEMPT="$GITHUB_RUN_ATTEMPT"
        verify_run "$OWNER_RUN_ID" "$OWNER_ATTEMPT" "$owner_path" oaslananka in_progress "$owner_actor_id"
        # New versioned API returns the actual child run ID. Never retry a dispatch
        # with an ambiguous response, and never guess a run using a name/time search.
        child="$(printf '%s\n' '{"ref":"main"}' |
            api -X POST "$root/workflows/release-handoff-worker.yml/dispatches" --input - |
            jq -er '.workflow_run_id | select(type == "number" and . > 0 and floor == .) | tostring')"
        positive_id "$child" || fail 'invalid dispatched run ID'
        [[ "$child" != "$OWNER_RUN_ID" ]] || fail 'self handoff'
        printf 'Dispatched worker run %s\n' "$child"
        # A bounded wait; failure, cancellation, missing identity or timeout fails closed.
        completed=false
        for ((poll=0; poll<60; poll++)); do
            status="$(api "$root/runs/$child" | jq -er '.status')"
            if [[ "$status" == completed ]]; then
                completed=true
                break
            fi
            case "$status" in queued|in_progress|waiting|requested|pending) ;; *) fail 'unexpected worker status';; esac
            sleep 5
        done
        [[ "$completed" == true ]] || fail 'worker timeout'
        verify_run "$child" 1 "$worker_path" 'github-actions[bot]' completed "$worker_actor_id"
        # Exact run-scoped receipt; no archive extraction or execution of downloaded bytes.
        metadata="$(api "$root/runs/$child/artifacts?per_page=100" |
            jq -ce --arg child "$child" --arg sha "$GITHUB_SHA" '
            select(.total_count == 1 and (.artifacts|length) == 1) | .artifacts[0] |
            select(.name == "handoff-receipt-1" and .expired == false and
                .workflow_run.id == ($child|tonumber) and .workflow_run.head_sha == $sha and
                .workflow_run.head_branch == "main" and
                .size_in_bytes > 0 and .size_in_bytes <= 16384 and
                (.digest|test("^sha256:[a-f0-9]{64}$")))')"
        artifact_id="$(jq -er '.id|tostring' <<<"$metadata")"
        positive_id "$artifact_id" || fail 'invalid receipt artifact ID'
        archive_digest="$(jq -er '.digest|sub("^sha256:";"")' <<<"$metadata")"
        scratch="$(mktemp -d)"
        trap 'rm -f -- "$scratch/receipt.zip" "$scratch/actual.json" "$scratch/expected.json"; rmdir -- "$scratch"' EXIT
        api "$root/artifacts/$artifact_id/zip" > "$scratch/receipt.zip"
        [[ "$(wc -c < "$scratch/receipt.zip")" -eq "$(jq -er '.size_in_bytes' <<<"$metadata")" ]] || fail 'archive size mismatch'
        [[ "$(sha256sum "$scratch/receipt.zip" | cut -d' ' -f1)" == "$archive_digest" ]] || fail 'archive digest mismatch'
        [[ "$(unzip -Z1 "$scratch/receipt.zip")" == handoff-receipt.json ]] || fail 'unexpected receipt archive inventory'
        unzip -p "$scratch/receipt.zip" handoff-receipt.json | head -c 8193 > "$scratch/actual.json"
        receipt "$child" > "$scratch/expected.json"
        cmp -s "$scratch/actual.json" "$scratch/expected.json" || fail 'receipt mismatch'
        verify_run "$OWNER_RUN_ID" "$OWNER_ATTEMPT" "$owner_path" oaslananka in_progress "$owner_actor_id"
        cat "$scratch/actual.json"
        printf 'Verified rehearsal receipt artifact %s (no publication)\n' "$artifact_id"
        ;;
    *) fail 'expected owner or worker';;
esac

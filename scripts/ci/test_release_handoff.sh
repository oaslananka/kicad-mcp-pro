#!/usr/bin/env bash
# Exercise actual entrypoints offline using fixed API responses and ZIP bytes.
set -euo pipefail
unset GH_TOKEN GITHUB_TOKEN
script="$PWD/scripts/rehearse_release_handoff.sh"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
cd "$scratch"
export GITHUB_REPOSITORY=oaslananka/kicad-mcp-pro GITHUB_REF=refs/heads/main
export GITHUB_EVENT_NAME=workflow_dispatch
export GITHUB_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
export GITHUB_RUN_ID=10 GITHUB_RUN_ATTEMPT=1
export GITHUB_ACTOR=oaslananka GITHUB_ACTOR_ID=285490571 GITHUB_TRIGGERING_ACTOR=oaslananka
export FAKE_API="$scratch"
printf '%s\n' '{"version":"4.23.0"}' > server.json

git() { [[ "$*" == 'rev-parse HEAD' ]] || return 97; printf '%s\n' "$GITHUB_SHA"; }
gh() {
    local subcommand="$1" header_flag="$2" version_header="$3"
    [[ "$subcommand" == api && "$header_flag" == -H && "$version_header" == 'X-GitHub-Api-Version: 2026-03-10' ]] || return 97
    shift 3
    local mock_root="repos/$GITHUB_REPOSITORY/actions"
    case "$*" in
        "$mock_root/runs/10") cat "$FAKE_API/owner.json";;
        "$mock_root/runs/20") cat "$FAKE_API/worker.json";;
        "$mock_root/workflows/release-handoff-rehearsal.yml/runs?branch=main&event=workflow_dispatch&status=in_progress&head_sha=$GITHUB_SHA&per_page=100")
            cat "$FAKE_API/owners.json";;
        "-X POST $mock_root/workflows/release-handoff-worker.yml/dispatches --input -")
            [[ ! -e "$FAKE_API/dispatch.json" ]] || return 98
            cat > "$FAKE_API/dispatch.json"
            cat "$FAKE_API/dispatch-response.json";;
        "$mock_root/runs/20/artifacts?per_page=100") cat "$FAKE_API/artifacts.json";;
        "$mock_root/artifacts/30/zip") cat "$FAKE_API/receipt.zip";;
        *) return 97;;
    esac
}
export -f git gh

run_record() {
    local id="$1" actor="$2" actor_id="$3" path="$4"
    jq -n --arg repo "$GITHUB_REPOSITORY" --arg sha "$GITHUB_SHA" \
        --argjson id "$id" --arg actor "$actor" --argjson actor_id "$actor_id" --arg path "$path" '
        {id:$id,repository:{full_name:$repo,id:123},head_repository:{full_name:$repo,id:123},
         path:(".github/workflows/"+$path),event:"workflow_dispatch",head_branch:"main",
         head_sha:$sha,run_attempt:1,actor:{login:$actor,id:$actor_id},
         triggering_actor:{login:$actor,id:$actor_id},status:"in_progress",conclusion:null}'
}

reset_fixture() {
    rm -f dispatch.json handoff-receipt.json receipt.zip
    run_record 10 oaslananka 285490571 release-handoff-rehearsal.yml > owner.json
    run_record 20 'github-actions[bot]' 41898282 release-handoff-worker.yml > worker.json
    jq '{total_count:1,workflow_runs:[.]}' owner.json > owners.json
    printf '%s\n' '{"workflow_run_id":20}' > dispatch-response.json
}

change_json() {
    local file="$1" filter="$2"
    jq "$filter" "$file" > changed.json
    mv changed.json "$file"
}

worker_env() {
    export GITHUB_RUN_ID=20 GITHUB_ACTOR='github-actions[bot]' GITHUB_TRIGGERING_ACTOR='github-actions[bot]' GITHUB_ACTOR_ID=41898282
}

run_owner_case() (
    local scenario="$1"
    reset_fixture
    (worker_env; bash "$script" worker)
    change_json worker.json '.status="completed" | .conclusion="success"'
    if [[ "$scenario" == wrong-receipt ]]; then
        change_json handoff-receipt.json '.publicationAuthorized=true'
    fi
    if [[ "$scenario" == wrong-manifest ]]; then
        change_json handoff-receipt.json '.manifestSha256="wrong"'
    fi
    zip -q receipt.zip handoff-receipt.json
    local digest
    digest="$(sha256sum receipt.zip | cut -d' ' -f1)"
    jq -n --arg sha "$GITHUB_SHA" --arg digest "sha256:$digest" \
        --argjson size "$(wc -c < receipt.zip)" '
        {total_count:1,artifacts:[{id:30,name:"handoff-receipt-1",expired:false,
        workflow_run:{id:20,head_sha:$sha,head_branch:"main"},size_in_bytes:$size,digest:$digest}]}
        ' > artifacts.json
    case "$scenario" in
        failed-worker) change_json worker.json '.conclusion="failure"';;
        cancelled-worker) change_json worker.json '.conclusion="cancelled"';;
        stale-worker) change_json worker.json '.run_attempt=2';;
        wrong-digest) change_json artifacts.json '.artifacts[0].digest=("sha256:"+("0"*64))';;
        duplicate) change_json artifacts.json '.total_count=2 | .artifacts += .artifacts';;
        ambiguous-dispatch) printf '%s\n' '{}' > dispatch-response.json;;
        success|wrong-receipt|wrong-manifest) ;;
        *) printf 'unknown owner scenario: %s\n' "$scenario" >&2; return 1;;
    esac
    local result=0
    bash "$script" owner > owner-output.txt 2>&1 || result=$?
    if [[ "$scenario" == success ]]; then
        [[ "$result" == 0 ]]
        grep -F 'Verified rehearsal receipt artifact 30' owner-output.txt
    else
        [[ "$result" != 0 ]]
        if grep -qF 'Verified rehearsal receipt artifact' owner-output.txt; then return 1; fi
    fi
    jq -e '. == {ref:"main"}' dispatch.json >/dev/null
    printf 'PASS: owner %s\n' "$scenario"
)

run_worker_case() (
    local scenario="$1"
    reset_fixture
    worker_env
    case "$scenario" in
        wrong-actor) export GITHUB_ACTOR=someone-else;;
        wrong-actor-id) export GITHUB_ACTOR_ID=1;;
        wrong-source) change_json owner.json '.head_sha="wrong"';;
        inactive-owner) change_json owner.json '.status="completed"';;
        stale-owner) change_json owner.json '.run_attempt=2';;
        ambiguous-owner) change_json owners.json '.total_count=2 | .workflow_runs += .workflow_runs';;
        no-owner) change_json owners.json '.total_count=0 | .workflow_runs=[]';;
        rerun) export GITHUB_RUN_ATTEMPT=2;;
        *) printf 'unknown worker scenario: %s\n' "$scenario" >&2; return 1;;
    esac
    local result=0
    bash "$script" worker > worker-output.txt 2>&1 || result=$?
    [[ "$result" != 0 && ! -e handoff-receipt.json && ! -e dispatch.json ]]
    printf 'PASS: worker %s\n' "$scenario"
)

for scenario in success failed-worker cancelled-worker stale-worker wrong-digest wrong-receipt wrong-manifest duplicate ambiguous-dispatch; do
    run_owner_case "$scenario"
done
for scenario in wrong-actor wrong-actor-id wrong-source inactive-owner stale-owner ambiguous-owner no-owner rerun; do
    run_worker_case "$scenario"
done

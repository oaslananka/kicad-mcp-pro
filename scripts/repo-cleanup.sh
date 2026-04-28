#!/usr/bin/env bash
# Review-first repository cleanup. Never run unattended.
set -euo pipefail

APPLY="${1:-}"
REPO_CANONICAL="oaslananka/kicad-mcp-pro"
REPO_ORG="oaslananka-lab/kicad-mcp-pro"

say() { printf '\033[1;36m[plan]\033[0m %s\n' "$*"; }

run_or_print() {
  if [ "$APPLY" = "--apply" ]; then
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    "$@"
  else
    printf -v rendered '%q ' "$@"
    say "${rendered% }"
  fi
}

cutoff_unix() {
  date -d "$1 days ago" +%s 2>/dev/null || date -v-"$1"d +%s
}

cutoff_iso() {
  date -d "$1 days ago" --iso-8601=seconds 2>/dev/null || date -v-"$1"d +%FT%T
}

echo "== Local branches with gone upstream and older than 30 days =="
if command -v timeout >/dev/null 2>&1; then
  timeout 20s git fetch --all --prune || echo "Fetch timed out or failed; continuing with local remote-tracking data." >&2
else
  git fetch --all --prune || echo "Fetch failed; continuing with local remote-tracking data." >&2
fi
git for-each-ref --format='%(refname:short) %(upstream:track) %(committerdate:unix)' refs/heads \
  | awk -v cutoff="$(cutoff_unix 30)" '$2 ~ /gone/ && $3+0 < cutoff { print $1 }' \
  | grep -v '^chore/autonomy-setup$' \
  | while read -r br; do
      run_or_print git branch -D -- "$br"
    done || true

echo
echo "== Remote branches on canonical older than 90 days without open PRs =="
gh api -X GET "/repos/${REPO_CANONICAL}/branches?per_page=100" --jq '.[].name' \
  | grep -Ev '^(main|master|develop|gh-pages)$' \
  | grep -Ev '^(release|hotfix)/' \
  | while read -r br; do
      open_count=$(gh pr list --repo "$REPO_CANONICAL" --head "$br" --state open --json number --jq 'length')
      [ "$open_count" -gt 0 ] && continue
      sha=$(gh api "/repos/${REPO_CANONICAL}/branches/${br}" --jq '.commit.sha' 2>/dev/null) || continue
      last=$(gh api "/repos/${REPO_CANONICAL}/commits/${sha}" --jq '.commit.committer.date' 2>/dev/null) || continue
      if [[ "$last" < "$(cutoff_iso 90)" ]]; then
        run_or_print gh api -X DELETE "/repos/${REPO_CANONICAL}/git/refs/heads/${br}"
      fi
    done || true

echo
echo "== Remote branches on org mirror older than 90 days =="
gh api -X GET "/repos/${REPO_ORG}/branches?per_page=100" --jq '.[].name' \
  | grep -Ev '^(main|master|develop|gh-pages)$' \
  | grep -Ev '^(release|hotfix)/' \
  | while read -r br; do
      sha=$(gh api "/repos/${REPO_ORG}/branches/${br}" --jq '.commit.sha' 2>/dev/null) || continue
      last=$(gh api "/repos/${REPO_ORG}/commits/${sha}" --jq '.commit.committer.date' 2>/dev/null) || continue
      if [[ "$last" < "$(cutoff_iso 90)" ]]; then
        run_or_print gh api -X DELETE "/repos/${REPO_ORG}/git/refs/heads/${br}"
      fi
    done || true

echo
echo "== Manual review items =="
echo "Open PRs older than 60 days:"
gh pr list --repo "$REPO_CANONICAL" --state open --limit 200 \
  --json number,title,updatedAt,author \
  --jq '.[] | select(.updatedAt < (now - 60*86400 | todate)) | "  #\(.number) \(.title) (last: \(.updatedAt), by \(.author.login))"' || true

echo
echo "Draft PRs older than 30 days:"
gh pr list --repo "$REPO_CANONICAL" --state open --draft --limit 200 \
  --json number,title,updatedAt \
  --jq '.[] | select(.updatedAt < (now - 30*86400 | todate)) | "  #\(.number) \(.title) (last: \(.updatedAt))"' || true

echo
echo "Tags on canonical without a GitHub Release:"
git ls-remote --tags "https://github.com/${REPO_CANONICAL}.git" \
  | awk '{print $2}' | sed 's|refs/tags/||' | grep -v '\^{}' | sort -u > /tmp/canonical_tags.txt
gh release list --repo "$REPO_CANONICAL" --limit 200 --json tagName --jq '.[].tagName' | sort -u > /tmp/canonical_releases.txt
comm -23 /tmp/canonical_tags.txt /tmp/canonical_releases.txt | sed 's/^/  /' || true

echo
echo "Tag mismatch where org has tags canonical lacks:"
git ls-remote --tags "https://github.com/${REPO_ORG}.git" \
  | awk '{print $2}' | sed 's|refs/tags/||' | grep -v '\^{}' | sort -u > /tmp/org_tags.txt
comm -23 /tmp/org_tags.txt /tmp/canonical_tags.txt | sed 's/^/  /' || true

echo
if [ "$APPLY" != "--apply" ]; then
  echo "Dry run complete. Re-run with: bash scripts/repo-cleanup.sh --apply"
fi

#!/usr/bin/env bash
set -euo pipefail

branch="${1:-main}"
PUSH_TAGS="${PUSH_TAGS:-true}"

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is not clean." >&2
  exit 1
fi

ensure_remote() {
  local name="$1" url="$2"
  if ! git remote get-url "$name" >/dev/null 2>&1; then
    git remote add "$name" "$url"
  elif [ "$(git remote get-url "$name")" != "$url" ]; then
    git remote set-url "$name" "$url"
  fi
}

repo_name="$(basename "$(git rev-parse --show-toplevel)")"
ensure_remote personal "git@github.com:oaslananka/${repo_name}.git"
ensure_remote org "git@github.com:oaslananka-lab/${repo_name}.git"

git push personal "$branch"
git push org "$branch"
if [ "$PUSH_TAGS" = "true" ]; then
  git push personal --tags
  git push org --tags
fi

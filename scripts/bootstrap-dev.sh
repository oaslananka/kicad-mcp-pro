#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# Windows Git Bash can expose a Microsoft Store python3 alias that exists
# on PATH but exits unsuccessfully. Prefer a working Python interpreter.
for python_bin in python3 python; do
  if command -v "$python_bin" >/dev/null 2>&1 \
    && "$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    exec "$python_bin" "${repo_root}/scripts/dev_environment.py" "$@"
  fi
done

printf '%s\n' 'Python 3.10+ is required for bootstrap.' >&2
exit 2

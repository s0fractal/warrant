#!/usr/bin/env bash
# Run every scenario against the `warrant` command on PATH.
set -euo pipefail
cd "$(dirname "$0")"
for s in [1-5]-*.sh; do
  echo "== $s"
  bash "$s"
done
echo "all scenarios: ok"

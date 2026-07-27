#!/usr/bin/env bash
# Build the release-asset evidence packs.
#
# WHY: the North Star is "a stranger verifies in 15 minutes, offline, trusting
# nothing but the tool". Until now that quest silently required `git clone` +
# `python3 demos/air-canada/build.py`, because the pack's `.warrants/` store is
# generated, not committed. A stranger who followed the README got a pip install
# and then a dead end. This script produces the artifact that closes the gap: a
# self-contained zip a stranger can `curl` and verify with nothing else.
#
#   tools/build_release_packs.sh [outdir]     # default: dist/
#
# Attach the resulting zip + SHA256SUMS to the GitHub release.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/dist}"
mkdir -p "$OUT"

command -v zip >/dev/null || { echo "need: zip" >&2; exit 2; }
python3 -c 'import cryptography' 2>/dev/null || { echo "need: pip install cryptography" >&2; exit 2; }

VERSION="$(python3 - "$ROOT/pyproject.toml" <<'PY'
import re, sys
print(re.search(r'^version\s*=\s*"([^"]+)"', open(sys.argv[1]).read(), re.M).group(1))
PY
)"
echo "warrant version: $VERSION"

build_pack() {
  local demo="$1" name="$2"
  echo
  echo "--- $name ---"
  ( cd "$ROOT" && python3 "demos/$demo/build.py" >/dev/null )

  local src="$ROOT/demos/$demo/pack"
  [ -d "$src/.warrants/records" ] || { echo "no store built at $src" >&2; return 1; }

  # A pack must never ship a private key. Fail loudly rather than publish one.
  if find "$src" -type f \( -name '*.key' -o -name '*secret*' -o -name '*private*' \) | grep -q .; then
    echo "REFUSING: key-looking file inside $src" >&2; return 1
  fi
  if grep -rlI --exclude-dir=.git -e 'PRIVATE KEY' "$src" 2>/dev/null | grep -q .; then
    echo "REFUSING: 'PRIVATE KEY' found inside $src" >&2; return 1
  fi

  local stage; stage="$(mktemp -d)"
  cp -R "$src" "$stage/$name"
  ( cd "$stage" && zip -q -r -X "$OUT/$name.zip" "$name" )
  rm -rf "$stage"
  echo "built: $OUT/$name.zip ($(find "$src" -type f | wc -l | tr -d ' ') files)"

  # Self-check: verify the ZIP the way a stranger will — unzipped, from a clean
  # directory, with no repo on the path.
  local probe; probe="$(mktemp -d)"
  ( cd "$probe" && unzip -q "$OUT/$name.zip" )
  local report
  report="$(cd "$probe" && python3 "$ROOT/impl/warrant.py" --store "$name/.warrants" verify --store-mode --json)"
  python3 - "$report" <<'PY'
import json, sys
r = json.loads(sys.argv[1])
assert r["report"] == "warrant.verify-report@v0", r
assert r["ok"] is True and r["errors"] == 0, r
print(f"  self-check: ok=true records={r['records']} errors=0 warnings={r['warnings']}")
PY
  rm -rf "$probe"
}

build_pack air-canada   "air-canada-pack"
build_pack cross-vendor "cross-vendor-pack"

( cd "$OUT" && shasum -a 256 ./*.zip > SHA256SUMS 2>/dev/null || sha256sum ./*.zip > SHA256SUMS )
echo
echo "--- release assets in $OUT ---"
cat "$OUT/SHA256SUMS"

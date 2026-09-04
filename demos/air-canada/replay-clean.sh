#!/usr/bin/env bash
# One command: replay the air-canada specimen through the PUBLIC `warrant` CLI,
# installed from a wheel built at THIS commit, in a fresh virtual environment,
# from a temporary directory outside the checkout.
#
#   bash demos/air-canada/replay-clean.sh
#
# What it does NOT do: download a published release (which may predate this
# checkout and would then be presented as if it were HEAD), import anything
# from impl/, or leave state behind. Each of those is a way to make a replay
# pass for the wrong reason.
#
# Network: building the wheel (isolated build fetches setuptools) and installing
# it (fetches `cryptography`) need PyPI unless a cache serves them. Set
# WARRANT_REPLAY_WHEEL=<path.whl> to reuse a wheel already built from this
# commit (CI does; it must still be built from the same tree).
# WARRANT_REPLAY_KEEP=1 keeps the temporary directory for inspection.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PY="${PYTHON:-python3}"

refuse() { echo "REPLAY: REFUSED environment: $*" >&2; exit 3; }

TMP="$(mktemp -d)"
cleanup() { if [ "${WARRANT_REPLAY_KEEP:-0}" = "1" ]; then echo "kept: $TMP"; else rm -rf "$TMP"; fi; }
trap cleanup EXIT

WHEEL="${WARRANT_REPLAY_WHEEL:-}"
if [ -z "$WHEEL" ]; then
  # Run the build from $TMP, not from the checkout: a checkout that contains a
  # `build/` directory (setuptools leaves one) shadows the `build` package when
  # the current directory is first on sys.path, and `-m build` then fails with
  # "'build' is a package and cannot be directly executed".
  # `build` is the producer publish.yml uses. Without it, pip's own PEP 517
  # wheel builder makes the same call against the same tree; without either,
  # this is a refusal, never a download of a published wheel.
  if ( cd "$TMP" && "$PY" -c 'import build.__main__' ) 2>/dev/null; then
    ( cd "$TMP" && "$PY" -m build --wheel --outdir "$TMP/wheel" "$ROOT" ) >"$TMP/build.log" 2>&1 \
      || { tail -n 5 "$TMP/build.log" >&2; refuse "wheel build failed (see above)"; }
  elif "$PY" -m pip --version >/dev/null 2>&1; then
    ( cd "$TMP" && "$PY" -m pip wheel --no-deps --disable-pip-version-check \
        --wheel-dir "$TMP/wheel" "$ROOT" ) >"$TMP/build.log" 2>&1 \
      || { tail -n 5 "$TMP/build.log" >&2; refuse "wheel build (pip wheel) failed (see above)"; }
  else
    refuse "neither the 'build' module nor pip is available to build a wheel; set WARRANT_REPLAY_WHEEL"
  fi
  WHEEL="$(ls "$TMP"/wheel/warrant_verify-*.whl)"
fi
[ -f "$WHEEL" ] || refuse "no wheel at $WHEEL"
echo "wheel:    $WHEEL"
echo "          sha256=$("$PY" -c 'import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$WHEEL")"
echo "commit:   $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo '(not a git checkout)')"

"$PY" -m venv "$TMP/venv" || refuse "could not create a virtual environment"
"$TMP/venv/bin/python" -m pip install --quiet --disable-pip-version-check "$WHEEL" \
  || refuse "could not install the wheel into the fresh environment (network for 'cryptography'?)"

# The specimen, its frozen vector and the driver are COPIED out; the driver
# then runs from the temporary directory, so the checkout is neither the cwd
# nor on any import path.
cp -R "$HERE/pack" "$TMP/pack"
cp "$HERE/replay.json" "$HERE/replay.py" "$TMP/"
cd "$TMP"
env -u SIGMA_GLYPH -u WARRANT_SIGMA_DIFFERENTIAL -u PYTHONPATH \
  "$PY" replay.py --warrant "$TMP/venv/bin/warrant" --pack "$TMP/pack" --manifest "$TMP/replay.json"

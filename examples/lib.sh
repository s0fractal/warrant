# Shared helpers for the scenarios. Only the `warrant` command and python3 are used.
set -euo pipefail
WORK=$(mktemp -d "${TMPDIR:-/tmp}/warrant-example.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
S="$WORK/store"; T="$WORK/trust.json"
warrant init --store "$S" >/dev/null

# get FIELD [FIELD...] < json   -> prints the (nested, dot-separated) field values
get() { python3 -c '
import json, sys
d = json.load(sys.stdin)
for path in sys.argv[1:]:
    v = d
    for k in path.split("."):
        v = v[int(k)] if isinstance(v, list) else v[k]
    print(v if not isinstance(v, (dict, list)) else json.dumps(v, sort_keys=True))
' "$@"; }

# fields FIELD... < json  -> the values on one line, for `read A B C <<< "$(... | fields a b c)"`
fields() { get "$@" | tr '\n' ' '; }

# actor NAME  -> creates $WORK/NAME.key and binds it in the trust file
actor() { warrant key --out "$WORK/$1.key" >/dev/null; warrant trust --trust "$T" --actor "$1" --key "$WORK/$1.key" >/dev/null; }

# as NAME warrant-subcommand ...  -> runs a signing subcommand as NAME
as() { local who=$1; shift; local sub=$1; shift; warrant "$sub" --store "$S" --key "$WORK/$who.key" --actor "$who" "$@"; }

expect() { # expect LABEL ACTUAL WANTED
  if [ "$2" = "$3" ]; then echo "  ok   $1: $2"; else echo "  FAIL $1: got '$2', expected '$3'" >&2; exit 1; fi; }

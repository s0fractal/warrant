#!/bin/sh
# Falsifier: two implementations MUST agree on every verification outcome
# (SPEC design rule, header). Feeds both verifiers the SAME envelope bytes —
# a schema-invalid body (float ts) — and requires BOTH to report an error.
# Exit 0 = agreement holds. Exit 1 = divergence (grounds for reject).
set -eu
cd "$(dirname "$0")/.."
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
mkdir -p "$T/store/records" "$T/store/blobs" "$T/flat"

cat > "$T/bad.json" <<'EOF'
{"body":{"warrant":"0.1","decision":"propose","subject":{"hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},"under":["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],"because":[],"evidence":[],"actor":{"id":"x@y"},"prior":[],"ts":1751700000.5},"sigs":[{"actor":"x@y","key":"0000000000000000000000000000000000000000000000000000000000000000","sig":"00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"}]}
EOF
cp "$T/bad.json" "$T/store/records/claimed-id.json"
cp "$T/bad.json" "$T/flat/bad.warrant.json"

py=0; python3 impl/warrant.py --store "$T/store" verify >/dev/null 2>&1 || py=$?
go_=0; ./impl-go/warrant-go verify "$T/flat" >/dev/null 2>&1 || go_=$?

echo "python verify exit: $py (nonzero expected: body is schema-invalid)"
echo "go     verify exit: $go_ (nonzero expected: same bytes)"
if [ "$py" -ne 0 ] && [ "$go_" -ne 0 ]; then
    echo "AGREE: both implementations reject the invalid record"
else
    echo "DIVERGENCE: implementations disagree on a verification outcome"
    exit 1
fi

# Differential canonicalization: the schema-reject case above only proves both
# reject one bad input. This proves both compute IDENTICAL WarrantIDs across the
# full JCS-escaping surface (every control byte, multibyte, astral, key order) —
# the check that actually enforces "agree on every WarrantID" (SPEC line 5).
echo "--- differential canonicalization ---"
python3 tests/differential.py

# Negative-path differential: both impls must agree on the DAMAGE too —
# tampered/stripped/forged signatures, tampered bodies, dangling priors,
# a hand-crafted ski@v1 verdict lie (Opus 4.8 review follow-up).
echo "--- negative-path differential ---"
python3 tests/negative.py

# v0.3 settlement differential: both impls must agree on settlement-active
# roots, genesis.json handling, threshold policies, re-litigation
# admissibility and key-state derivation (SPEC s5.1/s7/s9).
echo "--- settlement differential ---"
python3 tests/settlement.py

#!/bin/sh
# Run warrant-mcp over a mock storefront and produce a verifiable evidence pack
# of a shopping agent's session. The pack is generated fresh (real timestamps),
# so it is not committed — this is the point: watch your agent produce one.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
WARRANT="python3 $ROOT/impl/warrant.py"
PROXY="python3 $ROOT/integrations/mcp/warrant_mcp.py"

KEYDIR=$(mktemp -d)
$WARRANT keygen --out "$KEYDIR/agent.key" >/dev/null   # the agent's signing key
PACK="$HERE/pack"
rm -rf "$PACK"

echo ">>> shopping session (search=A0 skip, cart=A2, checkout+refund=A4, overspend=A4 error)"
# A shopping agent acting under a user's $200 mandate. The proxy forwards every
# call untouched and seals the consequential ones.
cat <<'JSON' | $PROXY --store "$PACK" --actor shopper-agent@demo --key "$KEYDIR/agent.key" \
        --effects "$HERE/effects.json" -- python3 "$HERE/shop_server.py" >/dev/null
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"shop.search_products","arguments":{"q":"headphones"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"shop.add_to_cart","arguments":{"sku":"A1"}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"shop.checkout","arguments":{"sku":"A1","amount":120}}}
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"shop.request_refund","arguments":{"sku":"B2","amount":60}}}
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"shop.overspend_attempt","arguments":{"amount":900}}}
JSON

rm -rf "$KEYDIR"
echo
echo ">>> verify the session — a merchant, the user, or a dispute handler, offline:"
$WARRANT --store "$PACK/.warrants" verify || true    # UNVERIFIABLE warns on the refused call are expected
echo
echo ">>> what the agent did (the sealed chain):"
DECISION=$(python3 -c "import json;print(json.load(open('$PACK/manifest.json'))['decision'])")
$WARRANT --store "$PACK/.warrants" why "$DECISION"
echo
echo "pack: $PACK   (4 sealed calls; the search was A0 and left out)"

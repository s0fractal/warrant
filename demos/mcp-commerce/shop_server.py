#!/usr/bin/env python3
"""Mock commerce MCP server for the warrant-mcp demo: a tiny storefront an agent
shops on behalf of a user. Newline-delimited JSON-RPC on stdio. `overspend_attempt`
returns an error (a spend beyond the user's mandate is refused by the store)."""
import json
import sys

RESULTS = {
    "shop.search_products": {"items": [{"sku": "A1", "price": 120}, {"sku": "B2", "price": 60}]},
    "shop.add_to_cart": {"cart": ["A1"], "subtotal": 120},
    "shop.checkout": {"order": "ORD-7788", "charged": 120, "currency": "USD"},
    "shop.request_refund": {"refund": "RF-2211", "amount": 60},
}


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        msg = json.loads(raw)
        mid = msg.get("id")
        if msg.get("method") == "tools/call":
            name = (msg.get("params") or {}).get("name", "")
            if name == "shop.overspend_attempt":
                result = {"isError": True, "content": [
                    {"type": "text", "text": "refused: amount exceeds user mandate ($200)"}]}
            else:
                result = {"content": [{"type": "text",
                                       "text": json.dumps(RESULTS.get(name, {"ok": name}))}]}
            resp = {"jsonrpc": "2.0", "id": mid, "result": result}
        else:
            resp = {"jsonrpc": "2.0", "id": mid, "result": {}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

# warrant-mcp, live — seal a shopping agent's session

This demo runs [`warrant-mcp`](../../integrations/mcp/) over a mock storefront and
produces a verifiable evidence pack of what a shopping agent did on a user's
behalf — the *agentic-commerce* case. When two parties later dispute a charge
(did the agent overspend? was that refund authorized?), they don't argue over the
merchant's logs: they re-verify the sealed session, offline, trusting neither side.

Nothing is pre-baked. Run it and watch a pack appear from a live session:

```bash
sh demos/mcp-commerce/run.sh
```

The agent acts under a user's $200 mandate. The proxy forwards every MCP call
untouched and seals the consequential ones:

| # | tool | class | sealed | outcome |
|---|------|-------|--------|---------|
| 1 | `shop.search_products` | A0 | no | (read-only) |
| 2 | `shop.add_to_cart` | A2 | yes | accept |
| 3 | `shop.checkout` ($120) | A4 spend | yes | accept |
| 4 | `shop.request_refund` ($60) | A4 transfer | yes | accept |
| 5 | `shop.overspend_attempt` ($900) | A4 spend | yes | **reject** (store refused: over mandate) |

The script then verifies the pack and walks the chain with `warrant why`:

```
REJECT … shop.overspend_attempt [A4]   - classified A4 (spend); error
  ACCEPT … shop.request_refund [A4]     - classified A4 (transfer); ok
    ACCEPT … shop.checkout [A4]         - classified A4 (spend); ok
      ACCEPT … shop.add_to_cart [A2]    - classified A2 (source_change); ok
```

`verify` reports **0 errors**. The warnings are honest, not failures: `binding
unverified` (you haven't supplied a keyring — bring your own with `--settlement
--trust-config`), and one `UNVERIFIABLE` on the refused call (a failed action's
reason is a recorded fact, not a re-runnable check).

## Why this matters

Agentic commerce (AP2, x402, agent checkout) standardizes the *intent* to pay —
but not the *evidence of what the agent actually did* when a charge is disputed.
A warrant chain is that evidence, and because it's verified from content-addressed
bytes, it settles a dispute between parties who share no trusted server. This is
the [strategy's](../../../Комерційне_застосування_стека_s0fractal/СТРАТЕГІЯ_ДІЙ.md)
expansion vector B, reachable from the same primitive as the regulated-industry
wedge.

The pack is generated fresh each run (real timestamps), so it isn't committed —
`run.sh` rebuilds it. To pin who the agent is, add a `trust.json` and re-verify
with `--settlement`, exactly as in the [Air Canada quest](../air-canada/).

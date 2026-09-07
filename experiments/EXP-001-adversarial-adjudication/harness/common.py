"""Shared names and the one path rule of the EXP-001 harness.

Every path a harness script accepts on its command line must resolve INSIDE
the experiment directory (`experiments/EXP-001-adversarial-adjudication/`):
runs go under `runs/` or `runs-scratch/`, the Planter's file is `PLANTS.json`
beside `commit_plants.py`. A path outside is refused, not normalised.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[1]

CALL = "tools/call"
SEARCH = "shop.search_products"
LIST_ORDERS = "shop.list_orders"
GET_ORDER = "shop.get_order"
ADD_TO_CART = "shop.add_to_cart"
CHECKOUT = "shop.checkout"
REFUND = "shop.request_refund"
CANCEL = "shop.cancel_order"
DECIDE = "mandate.decide"
SUMMARY = "session-summary.json"
ACTION_TOOL = {"refund": REFUND, "cancel": CANCEL, "purchase": CHECKOUT}
MODEL_RE = re.compile(r"^(scripted|[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._:-]*)$")


def inside(p, what="path", must_exist=False):
    """Resolve `p` and require it to lie inside the experiment directory."""
    q = Path(p).resolve()
    if q != EXP and EXP not in q.parents:
        sys.exit(f"{what} must be inside {EXP}: refusing {q}")
    if must_exist and not q.exists():
        sys.exit(f"{what} does not exist: {q}")
    return q


def final_json_block(text):
    """The LAST ```json fenced block of `text`, parsed, or None. The block is
    located by fences, not by a regex over its contents, so JSON strings may
    contain backticks, braces and escapes."""
    start = text.rfind("```json")
    if start < 0:
        return None
    body_start = text.find("\n", start)
    end = text.find("```", body_start if body_start >= 0 else start + 7)
    if body_start < 0 or end < 0:
        return None
    try:
        import json
        return json.loads(text[body_start:end].strip())
    except ValueError:
        return None


def valid_reply(rep):
    """The adjudicator's final block has the shape the prompt asked for."""
    return (isinstance(rep, dict) and isinstance(rep.get("verdict"), str) and isinstance(rep.get("defects"), list)
            and all(isinstance(d, dict) and "what" in d and "where" in d for d in rep["defects"])
            and isinstance(rep.get("unknowns"), list))


def model_id(m):
    if not MODEL_RE.match(m):
        sys.exit(f"model id {m!r} is not a vendor/model identifier")
    return m

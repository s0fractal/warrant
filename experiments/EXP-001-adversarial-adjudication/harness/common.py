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


def model_id(m):
    if not MODEL_RE.match(m):
        sys.exit(f"model id {m!r} is not a vendor/model identifier")
    return m

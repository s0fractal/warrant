"""The run budget, enforced: one ledger shared by both agent sessions and all
four adjudications (runs/budget.json). Before a paid request the caller
reserves a conservative upper bound (estimated prompt tokens x input ceiling
+ max completion tokens x output ceiling, x1.5); a reservation that would
take spent + reserved past the cap is refused BEFORE anything is sent and
recorded as a refusal. After the request the reservation is settled to the
provider's reported cost, or -- when the provider reports none -- the bound
itself stands as the charge (uncertain, counted in full).

A provider-side key limit is the second guard; this ledger is the one the
protocol can show.
"""
import fcntl
import json
import time
from pathlib import Path


class BudgetStopped(Exception):
    pass


class Budget:
    def __init__(self, path, cap_usd=None):
        self.path = Path(path)
        if not self.path.exists():
            if cap_usd is None:
                raise BudgetStopped(f"no budget ledger at {self.path} and no cap given")
            self._write({"cap_usd": float(cap_usd), "spent_usd": 0.0, "entries": []})

    def _read(self):
        return json.load(open(self.path))

    def _write(self, d):
        tmp = self.path.with_suffix(".tmp")
        json.dump(d, open(tmp, "w"), indent=1, sort_keys=True)
        tmp.replace(self.path)

    def _locked(self, fn):
        with open(self.path.with_suffix(".lock"), "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            d = self._read()
            try:
                out = fn(d)
            except BudgetStopped:
                self._write(d)               # the refusal is part of the ledger, not lost to the exception
                raise
            self._write(d)
            return out

    @staticmethod
    def bound(prompt_tokens_est, max_tokens, price):
        return 1.5 * (prompt_tokens_est * price["usd_per_m_in"] + max_tokens * price["usd_per_m_out"]) / 1e6

    def reserve(self, label, prompt_tokens_est, max_tokens, price):
        b = self.bound(prompt_tokens_est, max_tokens, price)

        def go(d):
            reserved = sum(e["usd"] for e in d["entries"] if e["status"] == "reserved")
            entry = {"id": len(d["entries"]), "label": label, "usd": round(b, 6), "ts": time.time()}
            if d["spent_usd"] + reserved + b > d["cap_usd"]:
                entry["status"] = "refused"
                d["entries"].append(entry)
                raise BudgetStopped(f"budget: {label} needs up to ${b:.4f}; spent ${d['spent_usd']:.4f} + reserved "
                                    f"${reserved:.4f} against cap ${d['cap_usd']:.2f} -- refused before sending")
            entry["status"] = "reserved"
            d["entries"].append(entry)
            return entry["id"]
        return self._locked(go)

    def settle(self, rid, usage):
        cost = (usage or {}).get("cost")

        def go(d):
            e = d["entries"][rid]
            if cost is None:
                e["status"] = "uncertain"          # the bound stands as the charge
                e["charged_usd"] = e["usd"]
            else:
                e["status"] = "settled"
                e["charged_usd"] = float(cost)
            d["spent_usd"] = round(d["spent_usd"] + e["charged_usd"], 6)
            return d["spent_usd"]
        return self._locked(go)

    def state(self):
        return self._read()


def est_tokens(text):
    return len(text.encode()) // 3 + 1

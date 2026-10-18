#!/usr/bin/env python3
"""The `warrant file` layer: structural members a session may omit, and `--id`.

Filling is a thin CLI convenience: a short body must file the very record the
full body files, and nothing semantic may be filled in.

    python3 tests/cli_test.py
"""
import contextlib
import io
import json
import re
import sys

from world import HOLDER, OWNER, W, World, check, finish

from warrant import cli  # noqa: E402  (world.py has put the implementation on sys.path)

AT = 500


class Session:
    def __init__(self):
        self.w = World()
        self.key = self.w.dir / "claude.key"
        self.key.write_text(self.w.keys[HOLDER].seed_hex() + "\n")

    def file(self, rtype, body, *extra):
        """(stdout, refusal) of one `warrant file` call."""
        argv = ["file", "--store", str(self.w.dir / "store"), "--key", str(self.key), "--actor", HOLDER,
                "--at", str(AT), "--type", rtype, *extra, json.dumps(body)]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                cli.main(argv)
        except SystemExit as e:
            return buf.getvalue(), str(e)
        return buf.getvalue(), None

    def body(self, rid):
        return W.loads(self.w.store.snapshot().records[rid])["record"]["body"]


def rid_of(out):
    return json.loads(out)["record"] if out else None


FULL_DUTY = {"statement": "parse() rejects empty input", "holder": HOLDER, "owed_to": [OWNER],
             "accept_by": [OWNER], "release_by": [], "condition": {"attest": {}}, "schedule": None,
             "requires": [], "serves": [], "answers": None, "subject": None}
SHORT_DUTY = {k: FULL_DUTY[k] for k in ("statement", "holder", "owed_to", "accept_by", "condition")}


def duty_cases():
    full, short = Session(), Session()
    full.w.keys = short.w.keys                     # one signer, two stores
    short.key.write_text(full.key.read_text())
    out_full, err_full = full.file("duty", FULL_DUTY)
    out_short, err_short = short.file("duty", SHORT_DUTY)
    check("F1", err_full is None and err_short is None and rid_of(out_short) == rid_of(out_full),
          "a duty body without its structural members files the same record as the full body",
          (err_full, err_short, out_full, out_short))
    s = Session()
    refused = []
    for member in ("statement", "holder", "owed_to", "accept_by", "condition"):
        _, err = s.file("duty", {k: v for k, v in SHORT_DUTY.items() if k != member})
        refused.append(err is not None and member in err)
    check("F2", all(refused), "a duty without a semantic member is still refused by name", refused)
    s = Session()
    parent, _ = s.file("duty", dict(SHORT_DUTY, statement="parent"))
    out, err = s.file("duty", dict(SHORT_DUTY, statement="child", serves=[rid_of(parent)]))
    check("F3", err is None and s.body(rid_of(out))["serves"] == [rid_of(parent)],
          "a structural member the body gives is kept as given", (err, out))
    _, err = Session().file("duty", dict(SHORT_DUTY, colour="red"))
    check("F4", err is not None and "colour" in err, "an unknown member is still refused", err)


def transition_cases():
    s = Session()
    d = rid_of(s.file("duty", SHORT_DUTY)[0])
    ev = s.w.evidence("log")
    item = {"duty": d, "act": "discharge", "evidence": [ev]}
    full = {"basis": "ATTESTED", "evidence": [ev], "relied_on": [], "established": ["it parses"],
            "residual": ["non-ASCII input not examined"], "opened": [], "closes": [item], "subject": None,
            "supersedes": [], "triggers": []}
    short = {k: full[k] for k in ("basis", "established", "residual", "closes")}
    out_full, err_full = s.file("transition", full)
    t = Session()
    t.key.write_text(s.key.read_text())
    t.file("duty", SHORT_DUTY)
    t.w.evidence("log")
    out_short, err_short = t.file("transition", short)
    check("T1", err_full is None and err_short is None and rid_of(out_short) == rid_of(out_full),
          "a transition body without its structural members (evidence = what its items cite) files the same record",
          (err_full, err_short))
    refused = []
    for member in ("basis", "established", "residual", "closes"):
        _, err = Session().file("transition", {k: v for k, v in short.items() if k != member})
        refused.append(err is not None and member in err)
    check("T2", all(refused), "a transition without a semantic member is still refused by name", refused)
    extra = s.w.evidence("more")
    out, err = s.file("transition", dict(short, evidence=[ev, extra] if ev < extra else [extra, ev]))
    check("T3", err is None and s.body(rid_of(out))["evidence"] == sorted([ev, extra]),
          "given transition evidence is kept, not replaced by the items' evidence", (err, out))


def id_cases():
    s = Session()
    out, err = s.file("duty", SHORT_DUTY, "--id")
    lines = out.splitlines()
    check("I1", err is None and len(lines) == 1 and re.fullmatch(r"[0-9a-f]{64}", lines[0]) is not None
          and lines[0] in s.w.store.snapshot().records,
          "--id prints only the new record id, one line", (err, out))
    out2, _ = Session().file("duty", SHORT_DUTY)
    check("I2", rid_of(out2) is not None and "type" in json.loads(out2), "without --id the output stays JSON", out2)


def main():
    duty_cases()
    transition_cases()
    id_cases()
    return finish("CLI")


if __name__ == "__main__":
    sys.exit(main())

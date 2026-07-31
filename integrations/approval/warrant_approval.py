#!/usr/bin/env python3
"""The approval boundary: record who asked, who sanctioned, and under which rules.

WHY THIS EXISTS
---------------
The MCP server (`integrations/mcp-server/`) lets an agent file its own decisions.
That is a real channel, and it has one structural blind spot: the agent chooses
what to record. Every record it produces is self-report. A store full of them
proves the bytes are intact and says nothing about whether anyone *else* agreed.

The decision point MCP cannot see is the one where the sanctioner is not the
agent -- a human answering an approval prompt, a policy engine returning
allow/deny, a reviewer releasing a paused workflow. Two things happen there that
happen nowhere else: a party with different custody says yes or no, and it says
so *against a stated rule*. That pair -- an independent decider and the rule it
applied -- is what a warrant is for, and it is exactly what a trace span cannot
carry, because a span is written by the agent's own process with the agent's own
credentials.

So this module records an approval as what it is: a `propose` filed by whoever
asked, answered by an `accept` or a `reject` filed by whoever sanctioned, both
`under` a policy blob that pins the rules in force.

WHAT IT DELIBERATELY IS NOT
---------------------------
**It is not a framework adapter.** It imports nothing but the standard library
and it never learns the name of a graph, a hook, or an agent runtime. Callers
hand it plain data. A binding to any particular framework is a dozen lines in
the caller's own approval loop -- `examples/langgraph_approval.py` is one, shown
as an example rather than shipped as a supported surface, because a maintained
adapter per framework is an M*N obligation this project cannot staff. See
`docs/integration-study.md` for that argument in full.

**It does not gate anything.** It records a decision somebody else made. If you
call `record_decision(allowed=True)` after denying the action, the store will
faithfully contain a signed lie. Warrant proves integrity and custody, never
that the prose is true in the world.

**It does not make one key into two parties.** This is the failure mode that
matters here, because the whole value of this boundary is that the decider is
independent. If the requester and the decider sign with the same key, they are
one custody wearing two names, and every claim of independent sanction collapses.
The module refuses to be quiet about it: `sanction_independent` is a field in the
returned record, computed from the actual public keys, not from the actor
strings the caller chose. `warrant verify` says the same thing from the other
side ("binding unverified (no keyring): key X claims actor Y").

HOW IT TALKS TO WARRANT
-----------------------
Through the CLI as a subprocess, never by importing internals -- the same choice
`integrations/mcp-server/server.py` makes and for the same reason: the bridge
then tracks exactly the released command surface, and `impl/` stays a dependency
of nothing.

USAGE
    python3 integrations/approval/warrant_approval.py selftest
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ApprovalError(Exception):
    """A filing could not be made. Never raised to mean 'denied'."""


class Boundary:
    """One approval boundary: a store, a policy, and two custodies.

    `requester_key` signs the request; `decider_key` signs the sanction. Passing
    the same path for both is allowed -- some deployments genuinely have one
    custody -- but it is then reported as such on every record, rather than
    being discovered later by whoever audits the store.
    """

    def __init__(self, store, policy_text, requester_key, decider_key,
                 warrant_cli=None):
        self.store = Path(store)
        self.cli = self._resolve_cli(warrant_cli)
        self._init_store()
        self.requester_key = Path(requester_key)
        self.decider_key = Path(decider_key)
        self.requester_pub = self._pubkey(self.requester_key)
        self.decider_pub = self._pubkey(self.decider_key)
        # Independence is a property of the KEYS, not of the actor strings.
        # Naming an actor "human" costs nothing and proves nothing.
        self.sanction_independent = self.requester_pub != self.decider_pub
        self.policy = self._add_policy(policy_text)

    # -- plumbing ---------------------------------------------------------
    @staticmethod
    def _resolve_cli(explicit):
        cand = explicit or os.environ.get("WARRANT_CLI")
        if cand:
            return [sys.executable, str(cand)] if str(cand).endswith(".py") else [str(cand)]
        local = ROOT / "impl" / "warrant.py"
        if local.is_file():
            return [sys.executable, str(local)]
        found = shutil.which("warrant")
        if found:
            return [found]
        raise ApprovalError("no warrant CLI: set WARRANT_CLI or install `warrant`")

    def _run(self, args):
        r = subprocess.run(self.cli + ["--store", str(self.store)] + args,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise ApprovalError(
                f"warrant {args[0]} failed: "
                f"{r.stderr.strip() or r.stdout.strip() or 'no output'}")
        return r

    def _init_store(self):
        if not (self.store / "records").is_dir():
            self._run(["init"])

    def _pubkey(self, key_path):
        """Read the public key this private key will sign as.

        Generates the key if absent -- but never inside the store, which is an
        evidence pack (see EVIDENCE-PACK.md); packs must not ship keys.
        """
        if not key_path.is_file():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            if key_path.resolve().is_relative_to(self.store.resolve()):
                raise ApprovalError(
                    f"refusing to create a signing key inside the store: {key_path}")
            r = subprocess.run(self.cli + ["keygen", "--out", str(key_path)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise ApprovalError(f"keygen failed: {r.stderr.strip()}")
        # `keygen` prints the pubkey; re-deriving it for an existing file means
        # asking the CLI, not parsing key bytes here.
        r = subprocess.run(self.cli + ["keygen", "--show", str(key_path)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            m = re.search(r"[0-9a-f]{64}", r.stdout)
            if m:
                return m.group(0)
        # No --show on this CLI version: fall back to the file's own content
        # hash. That is NOT the public key; it is only ever compared against
        # another value produced the same way, which is all independence needs.
        import hashlib
        return "sha256:" + hashlib.sha256(key_path.read_bytes()).hexdigest()

    def _add(self, kind, text):
        """Store free text as a blob and return its hash; pass a hash through.

        The store addresses rules and checks by content, so the caller may hand
        in either the text (stored here) or a hash it stored earlier. Accepting
        both is what lets a caller reuse one compiled ski@v1 check across many
        decisions without this module knowing what a ski term is.
        """
        if HEX64.match(str(text)):
            return str(text)                      # already a blob hash
        fd, tmp = tempfile.mkstemp(prefix=f"warrant-{kind}-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(str(text))
            return self._run([kind, "add", tmp]).stdout.strip().splitlines()[-1]
        finally:
            os.unlink(tmp)

    def _add_policy(self, text):
        return self._add("policy", text)

    def _file(self, argv, key):
        out = self._run(argv + ["--key", str(key)]).stdout.strip().splitlines()
        wid = out[-1] if out else ""
        if not HEX64.match(wid):
            raise ApprovalError(f"no warrant id in CLI output: {out!r}")
        return wid

    # -- the two verbs that matter ---------------------------------------
    def record_request(self, action, requester, reasons=(), evidence=()):
        """An actor asks to do `action`. Returns the propose WarrantID.

        `action` is free text describing the thing to be sanctioned; it is
        stored as the subject blob, so two identical requests hash alike and a
        reader can see exactly what was asked rather than a paraphrase.
        """
        if not str(action).strip():
            raise ApprovalError("action must be non-empty")
        fd, tmp = tempfile.mkstemp(prefix="warrant-action-")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(str(action))
            argv = ["propose", "--subject", tmp, "--under", self.policy,
                    "--note", f"requested: {str(action)[:120]}",
                    "--actor", str(requester)]
            for r in reasons:
                argv += ["--reason", str(r)]
            for e in evidence:
                argv += ["--evidence", str(e)]
            return self._file(argv, self.requester_key)
        finally:
            os.unlink(tmp)

    def record_decision(self, prior, allowed, decider, reasons=(),
                        check=None, runtime=None, verdict=None):
        """An independent actor sanctions or refuses `prior`.

        `allowed` picks accept vs reject and nothing else -- this records a
        decision, it does not make one. A re-runnable reason (`check` +
        `runtime` + `verdict`) is what turns the record from a claim into
        something a stranger can re-execute offline; prose-only rejects verify
        with an explicit UNVERIFIABLE warning, which is the honest outcome and
        not an error.
        """
        if not HEX64.match(str(prior)):
            raise ApprovalError("prior must be a hex64 WarrantID")
        argv = [("accept" if allowed else "reject"), str(prior),
                "--actor", str(decider)]
        for r in reasons:
            argv += ["--reason", str(r)]
        if check is not None:
            # A ski@v1 check MUST already be a compiled blob hash -- compiling a
            # term is authoring work with its own tooling (impl/ski_policy.py),
            # deliberately not hidden inside a recorder. A cmd@v1 check is text
            # naming a command, so it may be stored here.
            if runtime == "ski@v1" and not HEX64.match(str(check)):
                raise ApprovalError(
                    "a ski@v1 check must be a compiled blob hash; compile it "
                    "with impl/ski_policy.compile_check and pass the hash")
            argv += ["--check", self._add("blob", check),
                     "--runtime", runtime or "cmd@v1",
                     "--verdict", verdict or ("pass" if allowed else "fail")]
        return self._file(argv, self.decider_key)

    def record_approval(self, action, requester, decider, allowed,
                        request_reasons=(), decision_reasons=(), **kw):
        """The whole boundary in one call: request, then sanction.

        Returns a dict carrying both ids and -- the field that keeps this
        honest -- whether the two signatures came from different custodies.
        """
        req = self.record_request(action, requester, request_reasons)
        dec = self.record_decision(req, allowed, decider, decision_reasons, **kw)
        return {"request": req, "decision": dec,
                "allowed": bool(allowed),
                "requester": str(requester), "decider": str(decider),
                "policy": self.policy,
                "sanction_independent": self.sanction_independent,
                "store": str(self.store.resolve())}

    def verify(self):
        """The verify-report@v0 object exactly as the CLI emits it."""
        r = subprocess.run(
            self.cli + ["--store", str(self.store), "verify",
                        "--store-mode", "--json"],
            capture_output=True, text=True)
        line = r.stdout.strip()
        if not line:
            raise ApprovalError(f"verify produced no report: {r.stderr.strip()}")
        return json.loads(line)


# -- selftest -------------------------------------------------------------
def selftest():
    """Exercise the boundary end to end, including the cases that must fail.

    Framework-free on purpose: this runs on a clean checkout with no third-party
    package installed, which is why it can be wired into tools/check.py as a
    check that actually RUNS rather than one gated on an optional dependency.
    """
    import hashlib
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'ok  ' if cond else 'FAIL'}  {label}")
        ok = ok and bool(cond)

    tmpd = Path(tempfile.mkdtemp(prefix="warrant-approval-selftest-"))
    try:
        POLICY = ("Production deploys require a human sanction.\n"
                  "A refusal must name the missing precondition.\n")
        b = Boundary(store=tmpd / "store", policy_text=POLICY,
                     requester_key=tmpd / "agent.key",
                     decider_key=tmpd / "human.key")

        check("two keys are two custodies", b.sanction_independent is True)

        # 1. A refusal, which is the case the project exists for.
        denied = b.record_approval(
            "deploy build 9f2c to production",
            requester="agent:deployer", decider="human:sre",
            request_reasons=["tests green on 9f2c"],
            decision_reasons=["denied: no rollback plan recorded"],
            allowed=False)
        check("refusal filed with distinct ids",
              HEX64.match(denied["request"]) and HEX64.match(denied["decision"])
              and denied["request"] != denied["decision"])
        check("refusal reports independent sanction",
              denied["sanction_independent"] is True)

        # 2. An approval carrying a RE-EXECUTABLE reason -- the thing a trace
        #    span cannot do. The ski@v1 term is compiled with the repo's own
        #    authoring tooling (not part of the surface under test) and is
        #    re-executed by the CLI at filing time: if it did not reproduce the
        #    claimed verdict, `accept` would refuse to file at all.
        sys.path.insert(0, str(ROOT / "impl"))
        import warrant as W                                   # noqa: E402
        import ski_policy as sp                               # noqa: E402
        compiled = sp.compile_check(
            sp.And(sp.Fact("staging_only", True),
                   sp.Not(sp.Fact("customer_data", False))),
            W.Store(str(b.store)).put_blob)
        granted = b.record_approval(
            "rotate the staging database credential",
            requester="agent:ops", decider="human:sre",
            decision_reasons=["approved: staging only, blast radius bounded"],
            check=compiled.blob, runtime="ski@v1", verdict="pass",
            allowed=True)
        check("approval with a ski@v1 check files (verdict reproduced at filing)",
              HEX64.match(granted["decision"]))
        gbody = json.loads((b.store / "records" /
                            f"{granted['decision']}.json").read_text())
        gbody = gbody.get("body", gbody)
        check("the filed reason is a ski@v1 check, not prose",
              any(r.get("runtime") == "ski@v1"
                  for r in (gbody.get("because") or [])))

        # A ski@v1 check that is NOT a compiled blob must be refused rather than
        # silently stored as text that no verifier can re-execute.
        try:
            b.record_decision(granted["request"], True, "human:sre",
                              ["x"], check="staging_only", runtime="ski@v1")
            check("uncompiled ski@v1 check refused", False)
        except ApprovalError:
            check("uncompiled ski@v1 check refused", True)

        # 3. The chain is real: the decision names the request as its prior.
        rec = json.loads((b.store / "records" /
                          f"{denied['decision']}.json").read_text())
        body = rec.get("body", rec)
        # `prior` is a LIST in the stored body (SPEC §6), not a scalar -- the
        # first draft of this assertion compared it to a string and passed
        # nothing, which is why the check names the containment explicitly.
        check("decision links its request as prior",
              denied["request"] in (body.get("prior") or []))
        check("decision is a reject", body.get("decision") == "reject")
        check("both records cite the same policy",
              b.policy in (body.get("under") or []))

        # 4. The store verifies, and a prose-only reject is reported UNVERIFIABLE
        #    rather than silently accepted as evidence.
        rep = b.verify()
        check("store verifies ok", rep.get("ok") is True)
        check("records counted", rep.get("records") == 4)
        msgs = " | ".join(f["message"] for f in rep.get("findings", []))
        check("prose-only reject is flagged UNVERIFIABLE",
              "UNVERIFIABLE" in msgs)

        # 5. NEGATIVE CONTROL. Without this the four checks above only prove the
        #    verifier says yes; they never ask whether it can say no.
        victim = b.store / "records" / f"{denied['decision']}.json"
        original = victim.read_text()
        tampered = original.replace("no rollback plan recorded",
                                    "no rollback plan recordeD")
        check("tamper actually changed a byte", tampered != original)
        victim.write_text(tampered)
        rep2 = b.verify()
        check("one flipped byte makes the store fail", rep2.get("ok") is False)
        check("failure is reported as an error, not a warning",
              rep2.get("errors", 0) > 0)
        victim.write_text(original)
        check("restoring the byte restores the verdict",
              b.verify().get("ok") is True)

        # 6. One custody must NOT be able to pass itself off as two.
        shared = tmpd / "shared.key"
        b2 = Boundary(store=tmpd / "store2", policy_text=POLICY,
                      requester_key=shared, decider_key=shared)
        one = b2.record_approval("anything at all", requester="agent",
                                 decider="human:not-really", allowed=True)
        check("same key is reported as ONE custody",
              one["sanction_independent"] is False)

        # 7. Refusals to file nonsense.
        for label, fn in [
            ("empty action refused",
             lambda: b.record_request("   ", "agent")),
            ("non-hex prior refused",
             lambda: b.record_decision("not-a-hash", True, "human")),
            ("key inside the store refused",
             lambda: Boundary(store=tmpd / "store3", policy_text=POLICY,
                              requester_key=tmpd / "store3" / "k.key",
                              decider_key=tmpd / "d.key")),
        ]:
            try:
                fn()
                check(label, False)
            except ApprovalError:
                check(label, True)

    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    print("\napproval boundary selftest: " + ("ALL PASS" if ok else "FAILURES PRESENT"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["selftest"])
    return selftest() if ap.parse_args().command == "selftest" else 1


if __name__ == "__main__":
    sys.exit(main())

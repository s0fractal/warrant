#!/usr/bin/env python3
"""Application handoff for the dependency-audit pilot (s0fractal/warrant#151).

A producer freezes one *instance* per case (the frozen #150 input, the reviewed
encoder, the term and environment identities, the expected normal form and the
ATP accounting), pauses the Sigma computation and hands it over as signed Warrant
records. A receiver rebuilds the same instance from the exact wheel bytes and the
encoder on its own host, compares it field by field with what was sent, continues
the computation under its own provider and profile, files its own `compute` duty
and REPLAYED closure, and accepts the producer's handoff item exactly. The
producer reads the returned bytes back and replays the receipt itself.

    handoff.py produce --work DIR --packet OUT.json --manifest-sha256 PIN --wheelhouse CACHE
    handoff.py receive --work DIR --packet IN.json --packet-sha256 PIN --manifest-sha256 PIN
                       --accept-provider ID --wheelhouse CACHE --reply OUT.json
    handoff.py verify  --work DIR --packet IN.json --reply REPLY.json --reply-sha256 PIN
                       --manifest-sha256 PIN --wheelhouse CACHE
    handoff.py selftest --wheelhouse CACHE [--work DIR]

Every agent operation runs through the installed `warrant-agent` CLI in a fresh
process. Private keys never leave the work directory. Nothing here changes the
Warrant runtime, the SPEC, the provider or the kit; a matching computed answer
with a wrong instance binding is refused before any duty is filed, and a correct
replay never turns an unbound instance into application acceptance.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

from warrant import compute as P, engine as E, jcs as C, records as R
from warrant.keys import Key
from warrant.store import Store, Trust

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit as A          # noqa: E402  the kit's verifier
import evidence as EV      # noqa: E402  the kit's input-evidence binding

HERE = Path(__file__).resolve().parent
ENCODER_PATH = HERE.parent.parent / "work" / "dependency-audit-sigma" / "reach.py"
# The exact encoder bytes Codex accepted for sigma-glyph#68 (warrant c91ace0, round-3 acceptance).
ENCODER_SOURCE = "2348215116e81f6fdd492077e2491252ae8a968cb72e303886084fdbbf29d16e"
PROVIDER = A.PROVIDER
TARGET = "dependency-audit/predicate"
EXPERIMENT = "warrant-dependency-audit-handoff/1"
INSTANCE = "warrant-dependency-audit-instance/1"
CASES = ("base", "compute", "transitive-prohibited")
PACKET, REPLY, PROFILE, TRUST = "packet.json", "reply.json", "profile.json", "trust.json"
USES = {"continue": {"delivery": ["MATCH_EXPECTED_SET", "LOCAL_CAPTURE"],
                     "reliance": ["ELIGIBLE"], "fresh": True},
        "import": {"delivery": ["MATCH_EXPECTED_SET"]}}


class Refused(ValueError):
    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


def need(ok, code, detail=""):
    if not ok:
        raise Refused(code, detail)


def write(path, doc):
    Path(path).write_bytes(C.canon(doc))


def bounded(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
         "FILE", "expected a regular file <= 16 MiB")
    return path.read_bytes()


def pinned(path, pin):
    raw = bounded(path)
    need(C.digest(raw) == pin, "PACKET_PIN", "operator pin mismatch; nothing imported")
    return C.loads(raw)


def code_of(fn):
    """The refusal code a call ends in, or 'accepted'."""
    try:
        fn()
    except (Refused, A.Refused) as e:
        return e.code
    except Exception as e:  # noqa: BLE001 - the encoder has its own Refused class
        code = getattr(e, "code", None)
        if code is None:
            raise
        return code
    return "accepted"


# ----------------------------------------------------------------- application layer

_ENCODER = None


def encoder_bytes(path):
    need(path.is_file() and not path.is_symlink(), "ENCODER", str(path))
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == ENCODER_SOURCE, "ENCODER_SOURCE",
         f"{path.name} is not the reviewed encoder")
    return raw


def encoder():
    """The reviewed encoder, loaded from its exact bytes; any other bytes refuse."""
    global _ENCODER
    if _ENCODER is None:
        encoder_bytes(ENCODER_PATH)
        spec = importlib.util.spec_from_file_location("dependency_audit_reach", ENCODER_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        need(mod.SOURCE_SHA256 == ENCODER_SOURCE and mod.PROVIDER_ID == PROVIDER, "ENCODER", "identity")
        _ENCODER = mod
    return _ENCODER


def instance_of(evidence_doc, workload):
    """The application instance: what one computation is about, without host timing."""
    adm = workload["admission"]
    need(adm["state"] == "ADMITTED", "NOT_ADMITTED", "no verdict is derived from an inconclusive workload")
    need(workload["runtime"] == P.BOOK1, "RUNTIME", workload["runtime"])
    b = evidence_doc["binding"]
    return {"schema": INSTANCE, "case": b["case"], "case_kind": b["case_kind"],
            "manifest_sha256": b["manifest_sha256"], "source_commit": b["source_commit"],
            "contract_sha256": b["contract_sha256"], "audit_sha256": b["audit_sha256"],
            "target_sha256": b["target_sha256"], "artifact_ids": b["artifact_ids"],
            "binding_id": evidence_doc["binding_id"], "graph_sha256": b["graph_sha256"],
            "evaluation_sha256": b["evaluation_sha256"],
            "encoder": workload["encoder"], "encoder_source_sha256": workload["encoder_source_sha256"],
            "provider": workload["provider"], "runtime": workload["runtime"], "cost_model": workload["cost_model"],
            "program": workload["terms"]["program"], "input": workload["terms"]["input"],
            "environment": workload["environment_id"], "computation_id": workload["computation_id"],
            "expect": adm["expected_result"], "total_atp": adm["total_atp"], "pause_credit": adm["pause_credit"],
            "workload_id": workload["workload_id"]}


def application(pin, case, wheelhouse, supplied_workload=None):
    """Rebuild (evidence, workload, instance) for one case from the exact wheel bytes
    and the reviewed encoder. Every refusal of the kit or the encoder propagates;
    a supplied workload must equal the regenerated one (timing aside)."""
    need(case in CASES, "CASE", case)
    ev = EV.prepare(HERE / "fixture" / "manifest.json", pin, case, Path(wheelhouse))
    need(ev["state"] == "INPUT_VERIFIED_ENCODING_PENDING" and ev["artifact_binding"] == "WHEEL_BYTES_VERIFIED",
         "INPUT_STATE", ev["state"])
    enc = encoder()
    wl = enc.bind_workload(ev, supplied_workload)
    inst = instance_of(ev, wl)
    return ev, wl, inst


def public_workload(workload):
    """The workload without the host timing: the only float, and not a claim."""
    w = copy.deepcopy(workload)
    w["admission"].pop("oracle_wall_s", None)
    return w


def ski_of(evidence_doc):
    enc = encoder()
    ev, _ = enc.evaluation_of(evidence_doc)
    return enc.ski_text(enc.build(ev)[0])


def verdict_of(result_hash):
    v = encoder().VERDICT.get(bytes.fromhex(result_hash))
    need(v is not None, "RESULT", "normal form is neither K nor K I")
    return v


def same_instance(sent, local):
    """The sent instance must be exactly what this host rebuilt: a matching
    computation under another binding is refused, never credited."""
    need(isinstance(sent, dict) and sent == local, "BINDING",
         "sent instance is not what the frozen inputs and the reviewed encoder produce here")


# ----------------------------------------------------------------- parties

class Party:
    def __init__(self, root, name, peers, providers=(PROVIDER,)):
        self.root, self.name = Path(root).resolve(), name
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.key = Key.generate()
        keypath = self.root / "private.key"
        fd = os.open(keypath, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(self.key.seed_hex())
        self.store = Store(self.root / "store").init()
        self.profile = E.profile(uses={"continue": {"requires_triggers": False}},
                                 targets=[TARGET], providers=list(providers))
        write(self.root / PROFILE, self.profile)
        write(self.root / TRUST, Trust.document([(name, self.key.public), *peers]))
        self.doc = {"agent_api": "warrant-agent/1", "state": str(self.root / "state"),
                    "workspaces": {name: {"store": str(self.root / "store"),
                        "trust": str(self.root / TRUST), "profile": str(self.root / PROFILE),
                        "signer": {"actor": name, "key": str(keypath)}, "source_name": name,
                        "uses": USES, "expectations": {}, "limits": {}}}}
        self.save()
        prov = self.data("compute", op="provider")
        need(prov["provider"] == PROVIDER, "PROVIDER", f"installed provider {prov['provider']}")

    def save(self):
        write(self.root / "config.json", self.doc)

    def call(self, operation, **req):
        p = subprocess.run([str(Path(sys.executable).parent / "warrant-agent"), "--config",
                            str(self.root / "config.json"), operation, "-"],
                           input=json.dumps(dict(req, workspace=self.name)), text=True,
                           capture_output=True, timeout=1900, cwd=self.root)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            raise Refused("AGENT", f"exit {p.returncode}: {p.stderr[-400:]}") from None
        need(p.returncode == (0 if "ok" in out else 2), "AGENT", (p.returncode, p.stderr[-400:], out))
        return out

    def ok(self, operation, **req):
        out = self.call(operation, **req)
        need("ok" in out, "AGENT", out)
        return out["ok"]

    def data(self, operation, **req):
        return self.ok(operation, **req)["data"]

    def file(self, kind, body):
        return self.store.append(kind, self.name, int(time.time()), body, self.key)

    def context(self, *duties):
        return self.ok("context", actor=self.name, use="continue",
                       targets=[{"kind": "duty", "id": d} for d in duties])

    def capsule(self, duty):
        caps = self.context(duty)["data"]["capsules"]
        return next(c for c in caps if c["target"] == duty)

    def export(self, duties, request_id):
        view = self.context(*duties)
        return self.data("handoff", op="export", view_token=view["view_token"],
                         roots=[{"kind": "duty", "id": d} for d in duties], request_id=request_id)["package"]

    def inspect(self, pkg, duties, source):
        self.doc["workspaces"][self.name]["expectations"]["operator-pin"] = {
            "manifest": C.doc_id(pkg["manifest"]), "source": source, "exporter": source}
        self.save()
        return self.ok("handoff", op="inspect", manifest=pkg["manifest"], payload=pkg["payload"],
                       declaration=pkg["declaration"], expectation="operator-pin", actor=self.name,
                       targets=[{"kind": "duty", "id": d} for d in duties])

    def import_(self, pkg, duties, source, request_id):
        seen = self.inspect(pkg, duties, source)
        need(seen["delivery"]["relation"] == "MATCH_EXPECTED_SET", "DELIVERY", seen["delivery"])
        self.ok("handoff", op="import", staged_id=seen["data"]["staged_id"], request_id=request_id)
        snap = self.store.snapshot()
        good, bad = snap.authentic(Trust.load(self.root / TRUST))
        need(not bad and not snap.misfiled, "AUTHENTIC", (bad, snap.misfiled))
        return seen, snap, good

    def accept(self, duty, transition, request_id, view=None):
        """Accept item 0 of `transition` exactly; a fresh-process retry returns the same record."""
        view = view or self.context(duty)
        req = dict(based_on=view["view_token"], request_id=request_id, type="accept",
                   body={"transition": transition, "item": 0})
        first = self.data("commit", draft_id=self.data("prepare", **req)["draft_id"])
        before = len(self.store.snapshot().records)
        retry = self.data("commit", draft_id=self.data("prepare", **req)["draft_id"])
        need(first["record_id"] == retry["record_id"] and len(self.store.snapshot().records) == before,
             "RETRY", "a retried acceptance created another record")
        return first["record_id"]

    def set_providers(self, providers):
        write(self.root / PROFILE, dict(self.profile, providers=list(providers)))


# ----------------------------------------------------------------- producer

def produce(a):
    p = Party(a.work, "producer", [])
    cases, duties = {}, []
    for case in a.cases:
        ev, wl, inst = application(a.manifest_sha256, case, a.wheelhouse)
        t = p.data("compute", op="term", expr=ski_of(ev))
        need(t["input"] == inst["input"] and t["environment"] == inst["environment"], "IDENTITY",
             "the door's term identities differ from the encoder's")
        base = {"runtime": "book1", "input": inst["input"], "environment": inst["environment"]}
        s = p.data("compute", op="start", **base)
        r = p.data("compute", op="resume", **base, checkpoint=s["checkpoint"], state=s["state"],
                   credit=inst["pause_credit"])
        seg = r["segment"]
        need(seg["outcome"] == "PAUSED", "PAUSE", r)
        inst_b, ev_b, wl_b = p.store.put_json(inst), p.store.put_json(ev), p.store.put_json(public_workload(wl))
        d = p.file("duty", R.duty("producer",
            f"hand over the paused dependency audit '{case}': Sigma predicate over instance "
            f"{inst_b[:16]}, expected normal form {inst['expect'][:16]}",
            ["receiver"], {"attest": {}}, accept_by=["receiver"], subject=inst["manifest_sha256"]))
        evidence = [inst_b, ev_b, wl_b, seg["checkpoint"], seg["state"], inst["environment"]]
        tr = p.file("transition", R.transition("ATTESTED", evidence,
            closes=[R.item(d, "discharge", evidence)],
            established=[f"'{case}' paused after {inst['pause_credit']} of {inst['total_atp']} ATP under the "
                         f"reviewed encoder; instance {inst_b[:16]} binds manifest, graph, term and expected result"],
            residual=["the result is not computed here", "the receiver must rebuild the instance from exact "
                      "wheel bytes and replay the checkpoint", "the producer's provider report grants nothing"],
            subject=inst["manifest_sha256"]))
        cases[case] = {"instance": inst_b, "evidence": ev_b, "workload": wl_b, "duty": d, "transition": tr,
                       "paused": {"checkpoint": seg["checkpoint"], "state": seg["state"]},
                       "term": {"input": inst["input"], "environment": inst["environment"]},
                       "expect": inst["expect"], "total_atp": inst["total_atp"], "pause_credit": inst["pause_credit"]}
        duties.append(d)
    packet = {"experiment": EXPERIMENT, "producer_public": p.key.public, "provider": PROVIDER,
              "manifest_sha256": a.manifest_sha256, "encoder_source_sha256": ENCODER_SOURCE,
              "target": TARGET, "cases": cases, "package": p.export(duties, "handoff")}
    write(a.packet, packet)
    write(p.root / "sent.json", packet)
    out = {"packet_sha256": C.digest(a.packet.read_bytes()), "manifest": C.doc_id(packet["package"]["manifest"]),
           "producer_public": p.key.public,
           "cases": {k: {"instance": v["instance"], "duty": v["duty"], "expect": v["expect"],
                         "pause_credit": v["pause_credit"], "total_atp": v["total_atp"]} for k, v in cases.items()}}
    print(json.dumps(out, indent=2))
    return out


# ----------------------------------------------------------------- receiver

def binding_controls(pin, wheelhouse, sent_instance, workload, local_instance):
    """Refusals that must happen before any duty is filed. Each returns a code.
    `local_instance` is this host's rebuilt instance for the case; the sent-field
    controls compare against it without re-evaluating the term."""
    case = sent_instance["case"]
    cache = Path(wheelhouse).resolve()
    sel = next(a for a in C.loads((HERE / "fixture" / "manifest.json").read_bytes())["artifacts"]
               if a["origin"]["kind"] == "pypi")
    wheel = cache / sel["sha256"] / sel["filename"]

    def with_cache(mutate):
        tmp = Path(tempfile.mkdtemp(prefix="dependency-audit-cache-"))
        try:
            shutil.copytree(cache, tmp / "cache")
            mutate(tmp / "cache" / sel["sha256"] / sel["filename"])
            application(pin, case, tmp / "cache")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def altered(key, value):
        same_instance(dict(sent_instance, **{key: value}), local_instance)

    need(wheel.is_file(), "MISSING_WHEEL", str(wheel))
    return {
        "changed_wheel": code_of(lambda: with_cache(lambda w: w.write_bytes(w.read_bytes() + b"\0"))),
        "missing_wheel": code_of(lambda: with_cache(lambda w: w.unlink())),
        "wrong_operator_pin": code_of(lambda: application("0" * 64, case, wheelhouse)),
        "forged_graph_binding_same_answer": code_of(lambda: altered("graph_sha256", "0" * 64)),
        "wrong_environment": code_of(lambda: altered("environment", "0" * 64)),
        "wrong_root": code_of(lambda: altered("input", "0" * 64)),
        "stale_source_revision": code_of(lambda: altered("source_commit", "0" * 40)),
        "other_encoder": code_of(lambda: altered("encoder_source_sha256", "0" * 64)),
        "forged_expected_result": code_of(lambda: application(
            pin, case, wheelhouse, dict(workload, admission=dict(workload["admission"], expected_result="0" * 64)))),
        "forged_workload_id": code_of(lambda: application(pin, case, wheelhouse, dict(workload, workload_id="0" * 64))),
    }


EXPECTED_BINDING = {"changed_wheel": "WHEEL_DIGEST", "missing_wheel": "MISSING_WHEEL",
                    "wrong_operator_pin": "MANIFEST_PIN", "forged_graph_binding_same_answer": "BINDING",
                    "wrong_environment": "BINDING", "wrong_root": "BINDING", "stale_source_revision": "BINDING",
                    "other_encoder": "BINDING", "forged_expected_result": "WORKLOAD_MISMATCH",
                    "forged_workload_id": "WORKLOAD_MISMATCH"}


def receive(a):
    packet = pinned(a.packet, a.packet_sha256)
    need(packet["experiment"] == EXPERIMENT, "PACKET", "experiment")
    need(a.accept_provider == PROVIDER == packet["provider"], "PROVIDER", "operator provider choice")
    need(packet["manifest_sha256"] == a.manifest_sha256, "MANIFEST_PIN", "packet names another frozen instance")
    need(packet["encoder_source_sha256"] == ENCODER_SOURCE and packet["target"] == TARGET, "PACKET", "encoder/target")
    p = Party(a.work, "receiver", [("producer", packet["producer_public"])])
    pkg, sent = packet["package"], packet["cases"]
    duties = [c["duty"] for c in sent.values()]
    controls = {}
    seen = p.inspect(pkg, duties, "producer")
    need(seen["delivery"]["relation"] == "MATCH_EXPECTED_SET", "DELIVERY", seen["delivery"])
    damaged = copy.deepcopy(pkg)
    damaged["payload"]["blobs"].pop()
    bad = p.inspect(damaged, duties, "producer")
    blocked = p.call("handoff", op="import", staged_id=bad["data"]["staged_id"], request_id="damaged")
    controls["damaged_delivery"] = [bad["delivery"]["relation"], blocked.get("error")]
    need(controls["damaged_delivery"] == ["MISSING_DECLARED_BYTES", "IMPORT_BLOCKED"], "CONTROL", controls)
    seen, snap, good = p.import_(pkg, duties, "producer", "import")
    results, own = {}, []
    for case, c in sent.items():
        t0 = time.perf_counter()
        # 1. the instance is rebuilt here from exact wheel bytes and the reviewed encoder,
        #    with the sender's workload as a claim that must match (timing aside)
        ev, wl, inst = application(a.manifest_sha256, case, a.wheelhouse, snap.json_blob(c["workload"]))
        same_instance(snap.json_blob(c["instance"]), inst)
        need(c["instance"] == C.doc_id(inst) and snap.json_blob(c["evidence"]) == ev
             and c["term"] == {"input": inst["input"], "environment": inst["environment"]}
             and c["expect"] == inst["expect"], "BINDING", "packet metadata disagrees with the rebuilt instance")
        d, tr = good[c["duty"]], good[c["transition"]]
        need(d["actor"] == tr["actor"] == "producer" and d["type"] == "duty" and tr["type"] == "transition"
             and d["body"]["subject"] == inst["manifest_sha256"] and d["body"]["accept_by"] == ["receiver"]
             and tr["body"]["basis"] == "ATTESTED" and c["instance"] in tr["body"]["evidence"]
             and c["paused"]["checkpoint"] in tr["body"]["evidence"] and c["paused"]["state"] in tr["body"]["evidence"]
             and inst["environment"] in tr["body"]["evidence"]
             and R.item(c["duty"], "discharge", tr["body"]["evidence"]) in tr["body"]["closes"],
             "BINDING", "the signed handoff does not carry this instance and checkpoint")
        t = p.data("compute", op="term", expr=ski_of(ev))
        need(t["input"] == inst["input"] and t["environment"] == inst["environment"], "IDENTITY", "door term")
        # 2. refusals before any duty: same computed answer under a wrong binding stays unaccepted
        bc = binding_controls(a.manifest_sha256, a.wheelhouse, inst, wl, inst)
        need(bc == EXPECTED_BINDING, "CONTROL", bc)
        controls[case] = dict(bc)
        # 3. checked resume of the foreign prefix under this receiver's provider
        base = {"runtime": "book1", "input": inst["input"], "environment": inst["environment"],
                "checkpoint": c["paused"]["checkpoint"], "state": c["paused"]["state"]}
        remaining = inst["total_atp"] - inst["pause_credit"]
        other = p.data("compute", op="term", expr="K")["input"]
        wrong = p.data("compute", op="resume", **dict(base, input=other), credit=remaining, target=TARGET)
        controls[case]["wrong_root_resume"] = wrong["status"]
        need(wrong["status"] == "REFUSED" and "segment" not in wrong, "CONTROL", wrong)
        short = p.data("compute", op="resume", **base, credit=remaining - 1, target=TARGET)
        controls[case]["insufficient_budget"] = [short["segment"]["outcome"], "receipt" in short]
        need(short["segment"]["outcome"] == "PAUSED" and "receipt" not in short, "CONTROL", short)
        t1 = time.perf_counter()
        result = p.data("compute", op="resume", **base, credit=remaining, target=TARGET)
        t2 = time.perf_counter()
        need(result["status"] == "ADVANCED" and result["base_verification"]["basis"] == "REPLAYED"
             and result["segment"]["outcome"] == "NORMAL_FORM", "COMPUTE", result)
        need(result["segment"]["result"] == inst["expect"], "RESULT", "normal form differs from the admitted expectation")
        verdict = verdict_of(result["segment"]["result"])
        # 4. the receiver's own duty, compute condition and REPLAYED closure
        bd = p.file("duty", R.duty("receiver",
            f"dependency audit '{case}' over instance {c['instance'][:16]}: the Sigma predicate reaches "
            f"{inst['expect'][:16]}", ["producer"],
            {"compute": {"runtime": P.BOOK1, "input": inst["input"], "environment": inst["environment"],
                         "expect": inst["expect"]}}, subject=inst["manifest_sha256"]))
        closure = p.file("transition", R.transition("REPLAYED", [result["receipt"], c["instance"]],
            closes=[R.item(bd, "discharge", [result["receipt"]])],
            established=[f"replayed the producer's prefix and finished '{case}': predicate {verdict}"],
            residual=["the instance binding is this host's reconstruction, not a machine attestation",
                      "source/index completeness stays UNATTESTED"],
            subject=inst["manifest_sha256"]))
        p.set_providers([])
        un = p.capsule(bd)
        controls[case]["unaccepted_provider"] = un["disposition"]
        need(un["disposition"] != "DISCHARGED", "CONTROL", un)
        p.set_providers([PROVIDER])
        # one assessment per case: every receipt in the store is replayed by each one
        view = p.context(bd, c["duty"])
        caps = {x["target"]: x for x in view["data"]["capsules"]}
        need(caps[bd]["disposition"] == "DISCHARGED", "CLOSURE", caps[bd])
        # 5. exact acceptance of the producer's handoff item, stable under a fresh-process retry
        acc = p.accept(c["duty"], c["transition"], "accept-" + case, view)
        results[case] = {"instance": c["instance"], "verdict": verdict, "result": result["segment"]["result"],
                         "receipt": result["receipt"], "duty": bd, "transition": closure, "acceptance": acc,
                         "checkpoint": result["segment"]["checkpoint"], "state": result["segment"]["state"],
                         "credit": remaining, "total_atp": inst["total_atp"],
                         "wall_ms": {"rebuild_and_controls": int((t1 - t0) * 1000), "resume_incl_replay": int((t2 - t1) * 1000)}}
        own.append(bd)
    final = {x["target"]: x for x in p.context(*own, *duties)["data"]["capsules"]}
    need(all(final[d]["disposition"] == "DISCHARGED" for d in own + duties), "ACCEPT",
         {d[:16]: final[d]["disposition"] for d in own + duties})
    report = {"experiment": EXPERIMENT, "packet_sha256": a.packet_sha256, "manifest_sha256": a.manifest_sha256,
              "receiver_public": p.key.public, "provider": PROVIDER, "encoder_source_sha256": ENCODER_SOURCE,
              "host": {"platform": sys.platform, "python": sys.version.split()[0], "machine": os.uname().machine},
              "results": results, "controls": controls, "package": p.export(own, "return"),
              "remote_execution_basis": "receiver report; no machine attestation"}
    write(a.reply, report)
    out = {"reply_sha256": C.digest(a.reply.read_bytes()), "receiver_public": p.key.public,
           "results": {k: {"verdict": v["verdict"], "result": v["result"], "wall_ms": v["wall_ms"]} for k, v in results.items()},
           "controls": controls}
    if a.base64:
        out["reply_zlib_base64"] = base64.b64encode(zlib.compress(a.reply.read_bytes(), 9)).decode()
    print(json.dumps(out, indent=2))
    return report


# ----------------------------------------------------------------- producer-side readback

def verify(a):
    report = pinned(a.reply, a.reply_sha256)
    packet = C.loads(bounded(a.packet))
    need(report["experiment"] == EXPERIMENT and report["packet_sha256"] == C.digest(a.packet.read_bytes())
         and report["manifest_sha256"] == a.manifest_sha256 == packet["manifest_sha256"]
         and report["provider"] == PROVIDER and report["encoder_source_sha256"] == ENCODER_SOURCE,
         "REPLY", "reply is for another packet, instance or encoder")
    p = Party(a.work, "verifier", [("producer", packet["producer_public"]),
                                   ("receiver", report["receiver_public"])])
    own = [r["duty"] for r in report["results"].values()]
    seen, snap, good = p.import_(report["package"], own, "receiver", "return")
    out = {}
    for case, c in packet["cases"].items():
        r = report["results"][case]
        _, _, inst = application(a.manifest_sha256, case, a.wheelhouse)
        need(c["instance"] == C.doc_id(inst) and snap.json_blob(c["instance"]) == inst, "BINDING",
             "the sent instance is not what this host rebuilds")
        bd = good[r["duty"]]
        need(bd["actor"] == "receiver" and bd["type"] == "duty" and bd["body"]["condition"] == {"compute": {
            "runtime": P.BOOK1, "input": inst["input"], "environment": inst["environment"], "expect": inst["expect"]}}
             and bd["body"]["subject"] == inst["manifest_sha256"], "CONDITION", "receiver duty names another task")
        receipt = snap.json_blob(r["receipt"])
        need(receipt is not None and receipt["input"] == inst["input"] and receipt["environment"] == inst["environment"]
             and receipt["claimed"] == inst["expect"] == r["result"] and receipt["target"] == TARGET
             and receipt["checkpoint"] == r["checkpoint"] and receipt["state"] == r["state"], "RECEIPT", "unbound receipt")
        ck = snap.json_blob(receipt["checkpoint"])
        need(ck is not None and ck["parent_checkpoint_id"] == c["paused"]["checkpoint"], "CHAIN",
             "the returned checkpoint does not extend the sent one")
        closure = good[r["transition"]]
        need(closure["actor"] == "receiver" and closure["body"]["basis"] == "REPLAYED"
             and c["instance"] in closure["body"]["evidence"]
             and R.item(r["duty"], "discharge", [r["receipt"]]) in closure["body"]["closes"], "CLOSURE", "unbound closure")
        acc = good[r["acceptance"]]
        need(acc["actor"] == "receiver" and acc["type"] == "accept" and acc["body"]["transition"] == c["transition"]
             and acc["body"]["item"] == 0 and acc["body"]["evidence"] == good[c["transition"]]["body"]["evidence"],
             "ACCEPT", "acceptance is for another handoff or evidence set")
        need(verdict_of(r["result"]) == r["verdict"], "RESULT", "reported verdict disagrees with the result hash")
        out[case] = {"verdict": r["verdict"], "receipt": r["receipt"], "duty": r["duty"], "handoff": c["duty"]}
    # one assessment: this host replays every returned receipt once, under its own provider and profile
    caps = {x["target"]: x for x in p.context(*own, *[c["duty"] for c in packet["cases"].values()])["data"]["capsules"]}
    for case, o in out.items():
        cap = caps[o.pop("duty")]
        need(cap["disposition"] == "DISCHARGED" and any(x.startswith("REPLAYED:sigma-resume:") for x in cap["basis"]),
             "REPLAY", cap)
        need(caps[o.pop("handoff")]["disposition"] == "DISCHARGED", "ACCEPT", "producer handoff not discharged in readback")
        o.update(local_replay="PASS", disposition=cap["disposition"], basis=cap["basis"])
    summary = {"delivery": seen["delivery"]["relation"], "cases": out,
               "controls_reported": {k: v for k, v in report["controls"].items()},
               "host_reported": report["host"],
               "residual": "remote execution and the receiver's controls remain receiver-reported; "
                           "source/index completeness UNATTESTED"}
    print(json.dumps(summary, indent=2))
    return summary


# ----------------------------------------------------------------- local control

def selftest(a):
    base = Path(a.work) if a.work else Path(tempfile.mkdtemp(prefix="dependency-audit-handoff-"))
    base.mkdir(parents=True, exist_ok=True)
    pin = a.manifest_sha256
    passed = []

    def check(label, ok):
        need(ok, "SELFTEST", label)
        passed.append(label)
        print("PASS", label, flush=True)

    enc = encoder()
    check("encoder bytes are the reviewed ones", enc.SOURCE_SHA256 == ENCODER_SOURCE)
    other = base / "reach-other.py"
    other.write_bytes(ENCODER_PATH.read_bytes() + b"\n#\n")
    check("other encoder bytes refuse before use", code_of(lambda: encoder_bytes(other)) == "ENCODER_SOURCE")
    ev, wl, inst = application(pin, "base", a.wheelhouse)
    check("instance carries no host timing and hashes deterministically",
          "oracle_wall_s" not in C.canon(inst).decode() and C.doc_id(inst) == C.doc_id(instance_of(ev, wl)))
    check("supplied workload with other timing still binds", application(pin, "base", a.wheelhouse, dict(
        wl, admission=dict(wl["admission"], oracle_wall_s=0.0)))[2] == inst)
    pkt, rep = base / PACKET, base / REPLY
    cases = [a.case] if a.case else list(CASES)
    prod = produce(argparse.Namespace(work=base / "producer", packet=pkt, manifest_sha256=pin,
                                      wheelhouse=a.wheelhouse, cases=cases))
    check("producer paused every case", set(prod["cases"]) == set(cases))
    bad_pin = code_of(lambda: receive(argparse.Namespace(
        work=base / "receiver-bad-pin", packet=pkt, packet_sha256="0" * 64, manifest_sha256=pin,
        accept_provider=PROVIDER, wheelhouse=a.wheelhouse, reply=base / "unused-reply.json", base64=False)))
    check("wrong packet pin refuses before any import", bad_pin == "PACKET_PIN")
    other_inst = code_of(lambda: receive(argparse.Namespace(
        work=base / "receiver-other-instance", packet=pkt, packet_sha256=prod["packet_sha256"],
        manifest_sha256="1" * 64, accept_provider=PROVIDER, wheelhouse=a.wheelhouse, reply=base / "unused-reply.json",
        base64=False)))
    check("packet for another frozen instance refuses", other_inst == "MANIFEST_PIN")
    # a packet whose instance blob was swapped for one with the same term and answer but another graph binding
    tampered = C.loads(pkt.read_bytes())
    case0 = cases[0]
    blob_id = tampered["cases"][case0]["instance"]
    forged = dict(inst if case0 == "base" else application(pin, case0, a.wheelhouse)[2], graph_sha256="0" * 64)
    for b in tampered["package"]["payload"]["blobs"]:
        if b["id"] == blob_id:
            b["bytes_base64"] = base64.b64encode(C.canon(forged)).decode()
    tpkt = base / "packet-forged.json"
    write(tpkt, tampered)
    forged_code = code_of(lambda: receive(argparse.Namespace(
        work=base / "receiver-forged", packet=tpkt, packet_sha256=C.digest(tpkt.read_bytes()), manifest_sha256=pin,
        accept_provider=PROVIDER, wheelhouse=a.wheelhouse, reply=base / "unused-reply.json", base64=False)))
    check("swapped instance bytes are caught at delivery, never replayed", forged_code == "DELIVERY")
    report = receive(argparse.Namespace(work=base / "receiver", packet=pkt, packet_sha256=prod["packet_sha256"],
                                        manifest_sha256=pin, accept_provider=PROVIDER, wheelhouse=a.wheelhouse,
                                        reply=rep, base64=False))
    expect = {"base": True, "compute": True, "transitive-prohibited": False}
    check("receiver verdicts equal the frozen host references",
          all(report["results"][c]["verdict"] is expect[c] for c in cases))
    check("every binding control refused with its expected code",
          all({k: v for k, v in report["controls"][c].items() if k in EXPECTED_BINDING} == EXPECTED_BINDING for c in cases))
    summary = verify(argparse.Namespace(work=base / "verifier", packet=pkt, reply=rep,
                                        reply_sha256=C.digest(rep.read_bytes()), manifest_sha256=pin,
                                        wheelhouse=a.wheelhouse))
    check("producer-side readback replayed every returned receipt",
          all(v["local_replay"] == "PASS" for v in summary["cases"].values()))
    # reply metadata substitution: another case's receipt under this case's duty
    if len(cases) > 1:
        swapped = C.loads(rep.read_bytes())
        c0, c1 = cases[0], cases[1]
        swapped["results"][c0]["receipt"] = swapped["results"][c1]["receipt"]
        spath = base / "reply-swapped.json"
        write(spath, swapped)
        code = code_of(lambda: verify(argparse.Namespace(work=base / "verifier-swapped", packet=pkt, reply=spath,
                                                         reply_sha256=C.digest(spath.read_bytes()),
                                                         manifest_sha256=pin, wheelhouse=a.wheelhouse)))
        check("a receipt of another case under this case's duty is refused in readback", code == "RECEIPT")
    frozen = HERE / "round-1"
    if frozen.is_dir():
        pins = dict(line.split()[::-1] for line in (frozen / "SHA256SUMS").read_text().splitlines())
        for name in (PACKET, REPLY):
            check(f"round-1 {name} has its recorded digest", C.digest((frozen / name).read_bytes()) == pins[name])
        summary = verify(argparse.Namespace(work=base / "verifier-round-1", packet=frozen / PACKET,
                                            reply=frozen / REPLY, reply_sha256=pins[REPLY],
                                            manifest_sha256=pin, wheelhouse=a.wheelhouse))
        check("round-1 returned receipts replay locally and bind to locally rebuilt instances",
              all(v["local_replay"] == "PASS" for v in summary["cases"].values())
              and summary["host_reported"]["platform"] == "linux")
    print(f"DEPENDENCY-AUDIT HANDOFF: {len(passed)} controls PASS (local roles and frozen round-1 readback; "
          "remote execution not attested)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["produce", "receive", "verify", "selftest"])
    ap.add_argument("--work", type=Path, help="new private directory outside the checkout")
    ap.add_argument("--packet", type=Path)
    ap.add_argument("--packet-sha256")
    ap.add_argument("--reply", type=Path)
    ap.add_argument("--reply-sha256")
    ap.add_argument("--manifest-sha256", default=(HERE / "fixture" / "manifest.sha256").read_text().strip(),
                    help="the operator's pin of the frozen #150 manifest (default: the kit's own file)")
    ap.add_argument("--wheelhouse", type=Path, required=True)
    ap.add_argument("--accept-provider")
    ap.add_argument("--case", choices=CASES, help="selftest: local roundtrip on one case only (the frozen round-1 readback stays complete)")
    ap.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    ap.add_argument("--base64", action="store_true", help="receive: also print the reply as zlib+base64")
    args = ap.parse_args()
    try:
        if args.mode != "selftest":
            need(args.work is not None, "ARGS", "--work is required")
        {"produce": produce, "receive": receive, "verify": verify, "selftest": selftest}[args.mode](args)
    except (Refused, A.Refused) as exc:
        print(json.dumps({"status": "REFUSED", "code": exc.code, "detail": str(exc)}), file=sys.stderr)
        sys.exit(2)

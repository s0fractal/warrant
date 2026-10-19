#!/usr/bin/env python3
"""Bounded application input reconstruction; no Sigma or Warrant protocol changes."""
import argparse
import email.parser
import hashlib
import json
from pathlib import Path
import re
import sys
import urllib.parse
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version
import packaging

SCHEMA = "warrant-dependency-audit/1"
GRAPH_SCHEMA = "warrant-dependency-graph/1"
PROVIDER = "0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5"
ENV_KEYS = frozenset(default_environment())
MAX_WHEEL = 16 * 1024 * 1024
MAX_METADATA = 128 * 1024
HEX = re.compile(r"[a-f0-9]{64}\Z")


class Refused(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(f"{code}: {detail}")


def need(ok, code, detail):
    if not ok:
        raise Refused(code, detail)


def canon(doc):
    # Application encoding: ASCII JSON, sorted keys, compact separators; not a
    # new protocol canonicalizer. Every contracted field is ASCII, no floats.
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    def pairs(items):
        out = {}
        for key, value in items:
            need(key not in out, "JSON", "duplicate member")
            out[key] = value
        return out
    def no_number(value):
        raise Refused("JSON", "float/non-finite number")
    return json.loads(Path(path).read_bytes(), object_pairs_hook=pairs,
                      parse_float=no_number, parse_constant=no_number)


def fields(doc, keys):
    need(isinstance(doc, dict) and set(doc) == set(keys), "SCHEMA", f"expected {keys}")


def local(root, relative):
    need(isinstance(relative, str) and relative and not Path(relative).is_absolute()
         and ".." not in Path(relative).parts, "PATH", "relative fixture path")
    root = root.resolve()
    path = root
    for part in Path(relative).parts:
        path = path / part
        need(not path.is_symlink(), "PATH", "symlink inside the declared root")
    need(path.resolve().is_relative_to(root.resolve()), "PATH", "outside fixture")
    return path


def read_bounded(path, size=MAX_WHEEL):
    need(path.is_file(), "MISSING_WHEEL", str(path))
    need(not path.is_symlink() and path.stat().st_size <= size, "LIMIT", "file size/type")
    return path.read_bytes()


def metadata(raw):
    need(len(raw) <= MAX_METADATA, "LIMIT", "METADATA size")
    msg = email.parser.Parser().parsestr(raw.decode("utf-8", errors="strict"))
    need(not msg.defects, "METADATA", "email parsing defect")
    for name in ["Name", "Version"]:
        need(len(msg.get_all(name, [])) == 1, "METADATA", f"exactly one {name}")
    need(len(msg.get_all("Requires-Python", [])) <= 1, "METADATA", "duplicate Requires-Python")
    name = canonicalize_name(msg["Name"], validate=True)
    version = str(Version(msg["Version"]))
    requirements = msg.get_all("Requires-Dist", [])
    extras = sorted(canonicalize_name(x, validate=True) for x in msg.get_all("Provides-Extra", []))
    need(len(extras) == len(set(extras)) <= 4 and len(requirements) <= 32,
         "LIMIT", "extras/requirements")
    for text in [name, version, *requirements, *extras, msg.get("Requires-Python", "")]:
        need(text.isascii() and len(text) <= 4096, "METADATA", "ASCII/length contract")
    reqs = []
    for text in requirements:
        r = Requirement(text)
        need(r.url is None, "DIRECT_URL", "direct requirement URL outside this bounded profile")
        reqs.append(r)
    return {"name": name, "version": version, "extras": extras,
            "requires_python": msg.get("Requires-Python", ""), "requirements": reqs}


def read_wheel(path, artifact):
    raw = read_bounded(path)
    need(len(raw) == artifact["size"] and digest(raw) == artifact["sha256"], "WHEEL_DIGEST", artifact["filename"])
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        need(len(names) <= 2048 and len(names) == len(set(names)), "WHEEL", "duplicate/too many ZIP members")
        matches = [n for n in names if n.endswith(".dist-info/METADATA")]
        need(len(matches) == 1, "WHEEL", "exactly one METADATA")
        info = z.getinfo(matches[0])
        need(info.file_size <= MAX_METADATA, "LIMIT", "METADATA ZIP size")
        meta = z.read(info)
        # Distribution tags and Requires-Python are admission facts, not host imports.
        wheel_tags = [n for n in names if n.endswith(".dist-info/WHEEL")]
        need(len(wheel_tags) == 1 and z.getinfo(wheel_tags[0]).file_size < MAX_METADATA,
             "WHEEL", "exactly one bounded WHEEL")
        wheel_info = email.parser.Parser().parsestr(z.read(wheel_tags[0]).decode("ascii"))
        declared_tags = set(wheel_info.get_all("Tag", []))
    n, v, _, tags = parse_wheel_filename(artifact["filename"])
    need({str(t) for t in tags} == declared_tags, "WHEEL_TAGS", "filename/WHEEL tag mismatch")
    m = metadata(meta)
    need(n == artifact["name"] == m["name"] and str(v) == artifact["version"] == m["version"],
         "WHEEL_IDENTITY", "filename/METADATA/inventory mismatch")
    need(digest(meta) == artifact["metadata_sha256"], "METADATA_DIGEST", artifact["filename"])
    return meta, tags


def schema(doc):
    fields(doc, ["schema", "source", "tools", "contract_sha256", "target", "artifacts", "cases"])
    need(doc["schema"] == SCHEMA, "SCHEMA", "version")
    fields(doc["source"], ["repository", "commit", "source_date_epoch", "package_files", "observations_sha256"])
    need(doc["source"]["repository"] == "https://github.com/s0fractal/warrant"
         and re.fullmatch(r"[a-f0-9]{40}", doc["source"]["commit"]) is not None,
         "SOURCE", "repository/commit")
    need(type(doc["source"]["source_date_epoch"]) is int, "SOURCE", "epoch")
    need(isinstance(doc["source"]["observations_sha256"], str)
         and HEX.fullmatch(doc["source"]["observations_sha256"]), "SOURCE", "observation digest")
    files = doc["source"]["package_files"]
    need(isinstance(files, dict) and 0 < len(files) <= 128 and all(
        isinstance(n, str) and n.startswith(("warrant/", "warrant_agent/")) and ".." not in Path(n).parts
        and isinstance(h, str) and HEX.fullmatch(h) for n, h in files.items()), "SOURCE", "package file map")
    fields(doc["tools"], ["packaging", "collector_sha256", "audit_sha256", "build"])
    need(doc["tools"]["packaging"] == packaging.__version__ == "26.3", "TOOLCHAIN", "packaging must be 26.3")
    fields(doc["target"], ["marker_environment", "wheel_tags"])
    env = doc["target"]["marker_environment"]
    fields(env, ENV_KEYS)
    need(all(isinstance(v, str) and v.isascii() and len(v) <= 4096 for v in env.values()), "ENVIRONMENT", "marker values")
    need(".".join(env["python_full_version"].split(".")[:2]) == env["python_version"], "ENVIRONMENT", "Python versions disagree")
    tags = doc["target"]["wheel_tags"]
    need(isinstance(tags, list) and 0 < len(tags) <= 2048 and all(isinstance(t, str) and len(t) < 128 for t in tags)
         and tags == sorted(set(tags)), "LIMIT", "wheel tags")
    arts, cases = doc["artifacts"], doc["cases"]
    need(isinstance(arts, list) and 0 < len(arts) <= 32 and isinstance(cases, list) and 0 < len(cases) <= 8,
         "LIMIT", "artifact/case inventory")
    ids = set()
    for a in arts:
        fields(a, ["sha256", "filename", "size", "name", "version", "metadata_sha256", "metadata_file", "origin"])
        for key in ["sha256", "metadata_sha256"]:
            need(isinstance(a[key], str) and HEX.fullmatch(a[key]), "SCHEMA", key)
        need(a["sha256"] not in ids, "INVENTORY", "duplicate artifact")
        ids.add(a["sha256"])
        need(isinstance(a["filename"], str) and Path(a["filename"]).name == a["filename"]
             and a["filename"].isascii(), "PATH", "wheel basename")
        need(type(a["size"]) is int and 0 < a["size"] <= MAX_WHEEL, "LIMIT", "wheel size")
        need(a["name"] == canonicalize_name(a["name"], validate=True) and a["version"] == str(Version(a["version"])),
             "INVENTORY", "canonical name/version")
        origin = a["origin"]
        need(isinstance(origin, dict) and origin.get("kind") in ["pypi", "candidate", "synthetic"], "ORIGIN", "kind")
        fields(origin, ["kind", "url", "pypi_json"] if origin["kind"] == "pypi" else ["kind", "file"])
        if origin["kind"] == "pypi":
            u = urllib.parse.urlsplit(origin["url"])
            need(u.scheme == "https" and u.hostname == "files.pythonhosted.org" and not u.username
                 and not u.query and not u.fragment, "ORIGIN", "pinned public wheel URL")
            need(origin["pypi_json"] == f"https://pypi.org/pypi/{a['name']}/{a['version']}/json", "ORIGIN", "PyPI version URL")
    need(sum(a["size"] for a in arts) <= 64 * 1024 * 1024, "LIMIT", "total wheel bytes")
    names = set()
    for case in cases:
        fields(case, ["id", "kind", "artifact_ids", "root", "extras", "forbidden", "required", "graph", "graph_sha256", "reference"])
        need(isinstance(case["id"], str) and case["id"] not in names, "CASE", "unique id")
        names.add(case["id"])
        need(case["kind"] in ["real-install", "synthetic-control"], "CASE", "kind")
        selected = case["artifact_ids"]
        need(isinstance(selected, list) and 0 < len(selected) <= 16 and len(selected) == len(set(selected))
             and set(selected) <= ids, "INVENTORY", "case selection")
        for key in ["extras", "forbidden", "required"]:
            value = case[key]
            need(isinstance(value, list) and len(value) <= 4 and all(isinstance(x, str) and x == canonicalize_name(x, validate=True)
                 for x in value) and value == sorted(set(value)), "CASE", key)
        need(not set(case["forbidden"]) & set(case["required"]), "CASE", "inconsistent policy")
        need(case["root"] == canonicalize_name(case["root"], validate=True), "CASE", "root")


def inventory(doc, case):
    by_id = {a["sha256"]: a for a in doc["artifacts"]}
    out = {}
    for h in case["artifact_ids"]:
        a = by_id[h]
        need(a["name"] not in out, "INVENTORY", "multiple selected versions of one name")
        out[a["name"]] = a
    need(case["root"] in out, "INVENTORY", "root missing")
    if case["kind"] == "real-install":
        need(case["root"] == "warrant-loops" and out[case["root"]]["origin"]["kind"] == "candidate"
             and all(a["origin"]["kind"] != "synthetic" for a in out.values()), "SOURCE", "real case candidate provenance")
    return out


def reconstruct(doc, case, raw_metadata):
    selected = inventory(doc, case)
    metas = {n: metadata(raw_metadata[a["sha256"]]) for n, a in selected.items()}
    env = doc["target"]["marker_environment"]
    for n, m in metas.items():
        need(n == m["name"] and selected[n]["version"] == m["version"], "METADATA", "selected identity")
        need(not m["requires_python"] or SpecifierSet(m["requires_python"]).contains(env["python_full_version"], prereleases=True),
             "PYTHON", f"{n} does not support declared target")
    active = {case["root"]: set(case["extras"])}
    queue, edges = [case["root"]], set()
    while queue:
        name = queue.pop(0)
        m, requested = metas[name], active[name]
        need(requested <= set(m["extras"]), "EXTRA", f"unknown extra for {name}")
        for req in m["requirements"]:
            enabled = req.marker is None or any(req.marker.evaluate(environment=dict(env, extra=e), context="metadata")
                                                for e in ["", *sorted(requested)])
            if not enabled:
                continue
            dep = canonicalize_name(req.name, validate=True)
            need(dep in metas, "MISSING_DEPENDENCY", f"{name} -> {dep}")
            need(req.specifier.contains(metas[dep]["version"], prereleases=True), "VERSION", f"{name}: {req}")
            edges.add((name, dep))
            extra = {canonicalize_name(e, validate=True) for e in req.extras}
            if dep not in active or not extra <= active[dep]:
                active.setdefault(dep, set()).update(extra)
                queue.append(dep)
    need(set(active) == set(selected), "ORPHAN_INVENTORY", "selected wheels must exactly equal the reachable closure")
    names = sorted(set(selected) | set(case["forbidden"]) | set(case["required"]))
    need(len(names) <= 16 and len(edges) <= 64, "LIMIT", "graph vertices/edges")
    index = {n: i for i, n in enumerate(names)}
    graph = {"schema": GRAPH_SCHEMA,
             "nodes": [{"name": n, "version": metas[n]["version"] if n in metas else None,
                        "selected": n in metas, "extras": sorted(active.get(n, set()))} for n in names],
             "evaluation": {"n": len(names), "edges": sorted([index[x], index[y]] for x, y in edges),
                            "root": index[case["root"]], "forbidden": sorted(index[n] for n in case["forbidden"]),
                            "required": sorted(index[n] for n in case["required"])}}
    return graph


def reference(graph):
    # Standalone adjacency traversal; no dependency-marker or resolver code.
    g = graph["evaluation"]
    reached, paths = {g["root"]}, {g["root"]: [g["root"]]}
    for _ in range(g["n"]):
        new = {v for u, v in g["edges"] if u in reached}
        for u, v in g["edges"]:
            if u in paths and v not in paths:
                paths[v] = paths[u] + [v]
        if new <= reached:
            break
        reached |= new
    names = [v["name"] for v in graph["nodes"]]
    forbidden = sorted(reached & set(g["forbidden"]))
    absent = sorted(set(g["required"]) - reached)
    return {"predicate": not forbidden and not absent, "reachable": sorted(reached),
            "reachable_names": sorted(names[i] for i in reached),
            "forbidden_paths": [[names[i] for i in paths[v]] for v in forbidden],
            "missing_required": [names[i] for i in absent]}


def artifact_path(root, cache, a):
    if a["origin"]["kind"] != "pypi":
        return local(root, a["origin"]["file"])
    return local(cache, f"{a['sha256']}/{a['filename']}")


def fetch(doc, root, cache):
    for a in doc["artifacts"]:
        if a["origin"]["kind"] != "pypi":
            continue
        path = artifact_path(root, cache, a)
        if path.exists():
            read_wheel(path, a)
            continue
        # This is the only network path; only after the operator manifest pin.
        with urllib.request.urlopen(a["origin"]["url"], timeout=60) as response:
            need(urllib.parse.urlsplit(response.geturl()).hostname == "files.pythonhosted.org", "ORIGIN", "redirect")
            raw = response.read(a["size"] + 1)
        need(len(raw) == a["size"] and digest(raw) == a["sha256"], "WHEEL_DIGEST", a["filename"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


def verify(doc, root, cache, *, metadata_only=False):
    schema(doc)
    for field, path in [("audit_sha256", Path(__file__)), ("collector_sha256", root.parent / "collect.py")]:
        need(doc["tools"][field] == digest(path.read_bytes()), "TOOLCHAIN", field)
    need(doc["contract_sha256"] == digest((root.parent / "CONTRACT.md").read_bytes()), "CONTRACT", "contract identity")
    need(doc["source"]["observations_sha256"] == digest(read_bounded(root / "observations.json", 128 * 1024)),
         "SOURCE", "collector observation bytes")
    raw_metas, provider_ids = {}, []
    for a in doc["artifacts"]:
        meta = read_bounded(local(root, a["metadata_file"]), MAX_METADATA)
        need(digest(meta) == a["metadata_sha256"], "METADATA_DIGEST", a["filename"])
        _, _, _, tags = parse_wheel_filename(a["filename"])
        need(set(map(str, tags)) & set(doc["target"]["wheel_tags"]), "WHEEL_TAGS", "incompatible target")
        if not metadata_only:
            wheel = artifact_path(root, cache, a)
            observed, _ = read_wheel(wheel, a)
            need(observed == meta, "METADATA_DIGEST", "cached metadata differs from wheel")
            if a["origin"]["kind"] == "candidate":
                with zipfile.ZipFile(wheel) as z:
                    files = {n: digest(z.read(n)) for n in z.namelist()
                             if n.startswith(("warrant/", "warrant_agent/")) and not n.endswith("/")}
                need(files == doc["source"]["package_files"], "SOURCE", "candidate package files")
            if a["name"] == "sigma-glyph":
                with zipfile.ZipFile(wheel) as z:
                    files = {}
                    for name in ["sigma_glyph.py", "sigma_resume.py", "sigma_provider.py"]:
                        need(z.getinfo(name).file_size <= 1024 * 1024, "LIMIT", "provider source size")
                        files[name] = digest(z.read(name))
                identity = digest(canon({"provider": "sigma-resume", "files": files}))
                need(a["version"] == "0.8.0" and identity == PROVIDER, "PROVIDER", "reviewed source bytes")
                provider_ids.append(identity)
        raw_metas[a["sha256"]] = meta
    outcomes = []
    for case in doc["cases"]:
        graph = reconstruct(doc, case, raw_metas)
        need(canon(graph) == canon(case["graph"]) and digest(canon(graph)) == case["graph_sha256"], "GRAPH_BINDING", case["id"])
        answer = reference(graph)
        need(canon(answer) == canon(case["reference"]), "REFERENCE", case["id"])
        outcomes.append({"case": case["id"], "kind": case["kind"], "graph_sha256": case["graph_sha256"],
                         "evaluation_sha256": digest(canon(graph["evaluation"])), "reference": answer})
    need(metadata_only or provider_ids == [PROVIDER], "PROVIDER", "one pinned Sigma artifact")
    return {"binding": "METADATA_ONLY_UNVERIFIED" if metadata_only else "WHEEL_BYTES_VERIFIED",
            "manifest_sha256": digest(canon(doc)), "cases": outcomes,
            "provider_check": "NOT_RUN" if metadata_only else "MATCHED_REVIEWED_BYTES",
            "sigma_execution": "NOT_RUN", "source_completeness": "UNATTESTED"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode", choices=["fetch", "verify", "metadata-only"])
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--manifest-sha256", required=True)
    ap.add_argument("--wheelhouse", type=Path, required=True)
    args = ap.parse_args()
    try:
        raw = read_bounded(args.manifest, 1024 * 1024)
        need(digest(raw) == args.manifest_sha256, "MANIFEST_PIN", "operator pin mismatch")
        doc = load(args.manifest)
        need(canon(doc) == raw, "JSON", "noncanonical application manifest")
        schema(doc)
        root, cache = args.manifest.parent.resolve(), args.wheelhouse.resolve()
        if args.mode == "fetch":
            fetch(doc, root, cache)
        out = verify(doc, root, cache, metadata_only=args.mode == "metadata-only")
        print(json.dumps(out, sort_keys=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, UnicodeError) as e:
        print(json.dumps({"status": "REFUSED", "code": getattr(e, "code", "MALFORMED"), "detail": str(e)}))
        return 2


if __name__ == "__main__":
    sys.exit(main())

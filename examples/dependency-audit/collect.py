#!/usr/bin/env python3
"""Freeze already-observed pip installs, acquire exact wheels and rebuild inputs.

Acquisition is explicit; neither verifier nor replay resolves an index anew.
"""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name

import audit as A

SOURCE = "698afa9c5e27f9f30ea065c3b8f86bc2b682912a"


def public_bytes(url, limit):
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read(limit + 1)
    A.need(len(data) <= limit, "LIMIT", "download")
    return data


def synthetic(name, requirements):
    import io
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        stem = name.replace("-", "_") + "-2.0.0.dev0.dist-info/"
        for n, text in [("METADATA", "Metadata-Version: 2.3\nName: " + name + "\nVersion: 2.0.0.dev0\n"
                          + "".join("Requires-Dist: " + r + "\n" for r in requirements) + "\nSynthetic metadata-only control. Never install.\n"),
                        ("WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")]:
            info = zipfile.ZipInfo(stem + n, date_time=(2026, 10, 19, 0, 0, 0))
            z.writestr(info, text.encode())
    return out.getvalue(), name.replace("-", "_") + "-2.0.0.dev0-py3-none-any.whl"


def verify_source(package_files):
    for path, h in package_files.items():
        original = subprocess.check_output(["git", "show", f"{SOURCE}:{path}"],
                                           cwd=Path(__file__).resolve().parents[2])
        A.need(A.digest(original) == h, "SOURCE", path)


def collect_report(name, reports, env, candidate_id, cache, add):
    report = json.loads((reports / f"{name}-report.json").read_bytes())
    A.need(report["environment"] == env, "ENVIRONMENT", "pip report differs from collector environment")
    chosen = []
    for item in report["install"]:
        n, v = canonicalize_name(item["metadata"]["name"]), item["metadata"]["version"]
        if n == "warrant-loops":
            A.need(item["download_info"]["archive_info"]["hashes"]["sha256"] == candidate_id, "SOURCE", "report candidate")
            chosen.append(candidate_id)
            continue
        url = item["download_info"]["url"]
        sha = item["download_info"]["archive_info"]["hashes"]["sha256"]
        api = f"https://pypi.org/pypi/{n}/{v}/json"
        pypi = json.loads(public_bytes(api, 4 * 1024 * 1024))
        matches = [f for f in pypi["urls"] if f["url"] == url and f["digests"]["sha256"] == sha]
        A.need(len(matches) == 1, "ORIGIN", "pip report must match PyPI version JSON")
        entry = matches[0]
        A.need(urllib.parse.urlsplit(url).hostname == "files.pythonhosted.org" and url.startswith("https://"), "ORIGIN", url)
        filename = entry["filename"]
        wheelpath = cache / sha / filename
        data = wheelpath.read_bytes() if wheelpath.exists() else public_bytes(url, A.MAX_WHEEL)
        A.need(A.digest(data) == sha and len(data) == entry["size"], "WHEEL_DIGEST", filename)
        chosen.append(add(data, filename, {"kind": "pypi", "url": url, "pypi_json": api}))
    return sorted(chosen)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reports", type=Path, required=True, help="directory with base-report.json and compute-report.json")
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--observations", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--wheelhouse", type=Path, required=True)
    a = p.parse_args()
    root, cache = a.fixture.resolve(), a.wheelhouse.resolve()
    A.need(not root.exists(), "OUTPUT", "fixture must be new")
    root.mkdir(parents=True)
    observation_bytes = a.observations.read_bytes()
    A.need(len(observation_bytes) <= 128 * 1024, "LIMIT", "observations")
    (root / "observations.json").write_bytes(observation_bytes)
    artifacts, selected, raw_metas = {}, {}, {}

    def add(data, filename, origin):
        h = A.digest(data)
        where = cache / h / filename
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes(data)
        with zipfile.ZipFile(where) as z:
            members = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
            A.need(len(members) == 1, "METADATA", filename)
            meta = z.read(members[0])
        m = A.metadata(meta)
        if origin["kind"] != "pypi":
            rel = f"wheels/{h}/{filename}"
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            origin = {"kind": origin["kind"], "file": rel}
        meta_file = f"metadata/{h}.txt"
        (root / "metadata").mkdir(exist_ok=True)
        (root / meta_file).write_bytes(meta)
        desc = {"sha256": h, "filename": filename, "size": len(data), "name": m["name"], "version": m["version"],
                "metadata_sha256": A.digest(meta), "metadata_file": meta_file, "origin": origin}
        A.read_wheel(where, desc)
        artifacts[h], raw_metas[h] = desc, meta
        return h

    candidate = a.candidate.resolve()
    candidate_bytes = candidate.read_bytes()
    candidate_id = add(candidate_bytes, candidate.name, {"kind": "candidate"})
    with zipfile.ZipFile(candidate) as z:
        package_files = {n: A.digest(z.read(n)) for n in z.namelist()
                         if n.startswith(("warrant/", "warrant_agent/")) and not n.endswith("/")}
    verify_source(package_files)
    env = default_environment()
    for name in ["base", "compute"]:
        selected[name] = collect_report(name, a.reports, env, candidate_id, cache, add)
    sig = [h for h in selected["compute"] if artifacts[h]["name"] == "sigma-glyph"]
    A.need(len(sig) == 1 and artifacts[sig[0]]["version"] == "0.8.0", "VERSION", "Sigma pin")
    synthetic_ids = []
    for n, reqs in [("warrant-loops", ["audit-bridge==2.0.0.dev0"]), ("audit-bridge", ["sigma-glyph==0.8.0"])]:
        data, filename = synthetic(n, reqs)
        synthetic_ids.append(add(data, filename, {"kind": "synthetic"}))
    doc = {"schema": A.SCHEMA,
           "source": {"repository": "https://github.com/s0fractal/warrant", "commit": SOURCE,
                      "source_date_epoch": 1792428332, "package_files": package_files,
                      "observations_sha256": A.digest(observation_bytes)},
           "tools": {"packaging": version("packaging"), "collector_sha256": A.digest(Path(__file__).read_bytes()),
                     "audit_sha256": A.digest(Path(A.__file__).read_bytes()),
                     "build": {n: version(n) for n in ["build", "setuptools", "wheel", "pip"]}},
           "contract_sha256": A.digest((root.parent / "CONTRACT.md").read_bytes()),
           "target": {"marker_environment": env, "wheel_tags": sorted({str(t) for t in sys_tags()})},
           "artifacts": sorted(artifacts.values(), key=lambda x: x["sha256"]), "cases": []}
    for name, kind, ids, extras, forbidden, required in [
        ("base", "real-install", selected["base"], [], ["mcp", "sigma-glyph"], []),
        ("compute", "real-install", selected["compute"], ["compute"], ["mcp"], ["sigma-glyph"]),
        ("transitive-prohibited", "synthetic-control", sorted([*synthetic_ids, *sig]), [], ["mcp", "sigma-glyph"], [])]:
        case = {"id": name, "kind": kind, "artifact_ids": ids, "root": "warrant-loops", "extras": extras,
                "forbidden": forbidden, "required": required, "graph": None, "graph_sha256": None, "reference": None}
        graph = A.reconstruct(doc, case, raw_metas)
        case.update(graph=graph, graph_sha256=A.digest(A.canon(graph)), reference=A.reference(graph))
        doc["cases"].append(case)
    manifest = root / "manifest.json"
    manifest.write_bytes(A.canon(doc))
    result = A.verify(doc, root, cache)
    (root / "manifest.sha256").write_text(A.digest(manifest.read_bytes()) + "\n")
    (root / "reconstruction.json").write_bytes(A.canon(result))
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()

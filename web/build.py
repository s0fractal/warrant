#!/usr/bin/env python3
"""Build static Pages assets and the thin WASM adapter from this checkout."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "dist"

def run(*argv, **kw):
    subprocess.run(argv, check=True, cwd=ROOT, **kw)

def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for name in ("index.html", "style.css", "app.js", "worker.js", "client.js", "client.d.ts"):
        shutil.copyfile(HERE / name, OUT / name)
    shutil.copyfile(ROOT / "docs/conformance.html", OUT / "conformance.html")
    env = dict(os.environ)
    # Remap the checkout and the cargo registry out of the binary. Without this
    # rustc embeds absolute source paths (panic locations), so the WASM digest
    # recorded in build.json depended on WHERE it was built -- no one else could
    # reproduce it -- and the shipped bytes carried the builder's home path.
    cargo_home = os.environ.get("CARGO_HOME") or os.path.join(os.path.expanduser("~"), ".cargo")
    env["RUSTFLAGS"] = " ".join([
        "-C link-arg=-zstack-size=16777216",
        "-C link-arg=--max-memory=268435456",
        f"--remap-path-prefix={ROOT}=/warrant",
        f"--remap-path-prefix={cargo_home}=/cargo",
    ])
    run("cargo", "build", "--release", "--locked", "--target", "wasm32-unknown-unknown", "--manifest-path", "impl-wasm/Cargo.toml", env=env)
    run(os.environ.get("WASM_BINDGEN", "wasm-bindgen"), str(ROOT / "impl-wasm/target/wasm32-unknown-unknown/release/warrant_browser.wasm"), "--target", "web", "--out-dir", str(OUT / "wasm"), "--out-name", "warrant_browser")
    # The signed specimen already lives in this repository. Package its exact
    # bytes, not a newly signed claim about this website.
    ski = ROOT / "examples/ski"
    record = ski / "accept-ski.warrant.json"
    wid = "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0"
    files = {f"records/{wid}.json": record.read_bytes().hex()}
    sources = {f"records/{wid}.json": "examples/ski/accept-ski.warrant.json"}
    for p in [ski / "check.json", *sorted(ski.glob("*.bin"))]:
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        files[f"blobs/{h}"] = p.read_bytes().hex()
        sources[f"blobs/{h}"] = p.relative_to(ROOT).as_posix()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (OUT / "example.json").write_text(json.dumps({"files": files, "sources": sources, "sourceRevision": revision}, indent=2) + "\n")
    version = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "impl-rs/Cargo.toml").read_text(), re.M).group(1)
    identity = {"sourceRevision": revision, "coreVersion": version, "wasmSha256": hashlib.sha256((OUT / "wasm/warrant_browser_bg.wasm").read_bytes()).hexdigest(), "limits": {"bytes": 8388608, "files": 2048, "atpPerCheck": 1000000, "workerTimeoutMs": 12000}, "workingTree": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip() and "modified" or "clean"}
    (OUT / "build.json").write_text(json.dumps(identity, indent=2) + "\n")
    (OUT / ".nojekyll").touch()
    (OUT / "llms.txt").write_text("# Warrant browser verifier\n\nVerify signed, content-addressed decision records locally using the repository's Rust verifier compiled to WebAssembly.\n\n- Demo transport: ./example.json (path-to-hex file bytes; not a protocol extension)\n- Build identity and browser limits: ./build.json\n- Specification: https://github.com/s0fractal/warrant/blob/" + revision + "/SPEC.md\n- CLI-compatible output: warrant.verify-report@v0. ok means errors == 0; inspect warnings.\n- Signature validity does not establish actor identity, factual truth, or authorization.\n- Base grade is default. External trust-config JSON explicitly requests settlement grade, inheriting current implementation limits.\n- ski@v1 is re-executed. cmd@v1 is reported, never run in the browser.\n- Files remain in browser memory. No upload endpoint, analytics, or browser storage.\n")
    print(f"Built {OUT}; WASM { (OUT / 'wasm/warrant_browser_bg.wasm').stat().st_size } bytes")

if __name__ == "__main__":
    build()

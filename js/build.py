#!/usr/bin/env python3
"""Build both registry packages from the same WASM artifact and typed source."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

def build():
    subprocess.run([os.environ.get('PYTHON', 'python3'), 'web/build.py'], cwd=ROOT, check=True)
    generated = HERE / 'generated'
    generated.mkdir(exist_ok=True)
    wasm = ROOT / 'web/dist/wasm'
    for suffix in ('.js', '.d.ts'):
        shutil.copyfile(wasm / ('warrant_browser' + suffix), generated / ('warrant_browser' + suffix))
    raw = (wasm / 'warrant_browser_bg.wasm').read_bytes()
    (generated / 'bytes.js').write_text('export const binary = "' + base64.b64encode(raw).decode() + '";\n')
    (generated / 'bytes.d.ts').write_text('export const binary: string;\n')
    metadata = json.loads((ROOT / 'web/dist/build.json').read_text())
    metadata['packageVersion'] = json.loads((HERE / 'package.json').read_text())['version']
    assert metadata['packageVersion'] == json.loads((HERE / 'jsr.json').read_text())['version']
    assert metadata['packageVersion'] == metadata['coreVersion']
    assert metadata['wasmSha256'] == hashlib.sha256(raw).hexdigest()
    (generated / 'build.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # The glue is initialized from bundled bytes; its default URL fetch path is never used.
    dist = HERE / 'dist'
    if dist.exists():
        shutil.rmtree(dist)
    subprocess.run(['npx', '--yes', '--package=typescript@5.9.3', 'tsc', 'mod.ts', '--strict',
                    '--target', 'ES2022', '--module', 'ES2022', '--moduleResolution', 'bundler',
                    '--declaration', '--outDir', 'dist', '--skipLibCheck'], cwd=HERE, check=True)
    shutil.copytree(generated, dist / 'generated')
    shutil.copyfile(ROOT / 'LICENSE', HERE / 'LICENSE')
    print('npm and JSR artifacts built; embedded WASM SHA-256:', metadata['wasmSha256'])

if __name__ == '__main__':
    build()

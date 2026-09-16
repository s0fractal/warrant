"""Read the published holder at a pinned GitHub commit into a fresh store."""
import argparse
import importlib.util
import json
from pathlib import Path
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('w', ROOT / 'tools/witness.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
pin = (HERE / 'published-source.txt').read_text().strip()
assert len(pin) == 40 and all(c in '0123456789abcdef' for c in pin)
protocol = {'repository': 's0fractal/warrant', 'commit': pin,
            'holder': 'research-holder', 'custody': 'single-operator:s0fractal',
            'expected': ['without remote UNKNOWN', 'with remote LATER_STATE_WITNESSED'],
            'trust': 'local pinned public key and expected file digests; HTTPS transport'}
(out / 'protocol.json').write_bytes(w.canonical(protocol))
manifest = []
for local in sorted((HERE / 'evidence/holder').rglob('*.json')):
    relative = local.relative_to(HERE / 'evidence/holder')
    url = f'https://raw.githubusercontent.com/s0fractal/warrant/{pin}/experiments/wrt-012-cross-repo-001/evidence/holder/{relative.as_posix()}'
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(2097153)
    assert len(data) <= 2097152 and w.sha(data) == w.sha(local.read_bytes())
    dest = out / 'downloaded' / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    manifest.append({'url': url, 'sha256': w.sha(data), 'bytes': len(data)})
c0 = json.loads((HERE / 'evidence/results.json').read_bytes())['commitments'][0]
local = out / 'local'
(local / 'commitments').mkdir(parents=True)
(local / 'commitments' / f'{c0}.json').write_bytes((out / 'downloaded/commitments' / f'{c0}.json').read_bytes())
(local / 'tip').write_text(c0 + '\n')
cfg = json.loads((HERE / 'evidence/trusted-holders.json').read_bytes())['holders']
cfg[0]['store'] = str(out / 'downloaded')
before = w.build_report(local, c0, [])
after = w.build_report(local, c0, cfg)
assert before['freshness']['status'] == 'UNKNOWN'
assert after['freshness']['status'] == 'LATER_STATE_WITNESSED'
assert after['freshness']['steps'] == 2
for name, value in [('downloads', manifest), ('before', before), ('after', after)]:
    (out / f'{name}.json').write_bytes(w.canonical(value))
print('6/6 downloaded hashes; UNKNOWN -> LATER_STATE_WITNESSED, two verified links; same custody')

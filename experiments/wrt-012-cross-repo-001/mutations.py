"""Two deliberately weakened checkers must fail the experiment's assertions."""
from pathlib import Path
import argparse
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
p = argparse.ArgumentParser()
p.add_argument('--black-heart', required=True)
a = p.parse_args()
source = (ROOT / 'tools/witness.py').read_text()
mutations = {
    'always-unknown': ('if w["outcome"] == "COMPLETE" and fresh["status"] == "UNKNOWN":',
                       'if False and fresh["status"] == "UNKNOWN":'),
    'trust-sequence': ('if w["outcome"] == "COMPLETE" and fresh["status"] == "UNKNOWN":',
                       'if fresh["status"] == "UNKNOWN":'),
}
for name, (before, after) in mutations.items():
    assert source.count(before) == 1
    with tempfile.TemporaryDirectory(prefix='wrt012-mutation-') as temp:
        root = Path(temp)
        (root / 'tools').mkdir()
        (root / 'tools/witness.py').write_text(source.replace(before, after))
        driver = root / 'experiments/cross/run.py'
        driver.parent.mkdir(parents=True)
        driver.write_bytes((HERE / 'run.py').read_bytes())
        result = subprocess.run([sys.executable, '-B', str(driver), '--black-heart',
                                 str(Path(a.black_heart).resolve()), '--output', str(root / 'out')],
                                capture_output=True, text=True, timeout=30)
        assert result.returncode != 0 and 'AssertionError' in result.stderr, result.stderr
        endpoint = "report('B'" if name == 'always-unknown' else "report('C'"
        assert endpoint in result.stderr, result.stderr
        print(f'{name}: assertion killed at {endpoint}')

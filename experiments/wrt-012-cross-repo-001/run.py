"""Frozen Black-heart operands, Warrant verifier, Git-transported holder receipt.
Creates disposable repositories under a NEW output directory; no remote writes.
"""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('witness', ROOT / 'tools/witness.py')
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)
SOURCE = '816d36bed9e156ca1913ac45adbbe2b1ec8d2048'


def git(path, *args):
    directory = Path(path).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError('Git working directory must be a directory')
    return subprocess.check_output(['git', *args], cwd=directory,
                                   stderr=subprocess.PIPE, timeout=30)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--black-heart', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)

    def save(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(w.canonical(obj))

    def cli(*args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rc = w.main(list(map(str, args)))
        value = json.loads(buffer.getvalue())
        assert rc == 0, value
        return value

    operands = [git(a.black_heart, 'show', f'{SOURCE}:{name}')
                for name in ('CLI-VERIFY.md', 'artifact_audit.py')]
    protocol = {
        'type': 'wrt012.cross-repo-experiment@v1',
        'source': {'repository': 'https://github.com/s0fractal/black-heart', 'commit': SOURCE,
                   'files': dict(zip(('CLI-VERIFY.md', 'artifact_audit.py'), map(w.sha, operands)))},
        'checker_sha256': w.checker_sha256(), 'driver_sha256': w.sha(Path(__file__).read_bytes()),
        'custody': 'single-operator:s0fractal', 'external_independence': 'NOT_DEMONSTRATED',
        'transport': 'git local file transport into separate successor checkout',
        'endpoints': ['A no holder UNKNOWN', 'B cloned holder detects later linked state',
                      'C disconnected higher sequence UNKNOWN', 'D missing intermediate PATH_INCOMPLETE',
                      'E altered intermediate LINK_TAMPERED', 'F wrong holder key rejected',
                      'G joint rollback UNKNOWN', 'H byte verification does not change freshness'],
        'network_calls': 0, 'adoption': 'NOT_EVALUATED',
    }
    save(out / 'protocol.json', protocol)  # before signing or computing endpoints
    sender, holder, successor = (out / n for n in ('sender', 'holder', 'successor'))
    policy = {'type': w.BYTE_PROFILE, 'checker_sha256': w.checker_sha256(),
              'expected_sha256': w.sha(operands[0])}
    save(out / 'policy.json', policy)
    (out / 'subject.bin').write_bytes(operands[0])
    commitments = []
    for data in (operands[0], operands[1], operands[0]):
        r = cli('commit', '--store', sender, '--subject-kind', 'file',
                '--subject-sha256', w.sha(data), '--verifier-closure-sha256', w.sha(w.canonical(policy)),
                '--stream', w.sha(b'wrt012-cross-repo-001:black-heart'))
        commitments.append(r['commitment'])
    c0, c1, c2 = commitments
    # No private key is retained in the output or committed Git history.
    with tempfile.TemporaryDirectory(prefix='wrt012-signing-') as keydir:
        key = Path(keydir) / 'key'
        public = cli('keygen', '--out', key)['pubkey_hex']
        for c in commitments:
            cli('receive', '--holder-store', holder, '--holder-id', 'research-holder', '--key', key,
                '--commitment-file', sender / 'commitments' / f'{c}.json', '--observed', 'experiment-order-only')
    git(holder, 'init', '--initial-branch=main')
    git(holder, 'add', '.')
    git(holder, '-c', 'user.name=Experiment fixture', '-c', 'user.email=fixture@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'Fixture: retain three signed commitments')
    transport_commit = git(holder, 'rev-parse', 'HEAD').decode().strip()
    subprocess.run(['git', 'clone', '--no-hardlinks', str(holder), str(successor)],
                   check=True, capture_output=True, timeout=30)
    assert git(successor, 'rev-parse', 'HEAD').decode().strip() == transport_commit
    for path in holder.rglob('*.json'):
        assert path.read_bytes() == (successor / path.relative_to(holder)).read_bytes()
    # Successor sees an actual truncated sender store: C1/C2 absent, tip rolled back.
    local = out / 'rolled-back'
    local.mkdir()
    (local / 'commitments').mkdir()
    shutil.copyfile(sender / 'commitments' / f'{c0}.json', local / 'commitments' / f'{c0}.json')
    (local / 'tip').write_text(c0 + '\n')
    cfg = [{'id': 'research-holder', 'pubkey_hex': public, 'store': str(successor),
            'custody': 'single-operator:s0fractal'}]
    save(out / 'trusted-holders.json', {'holders': cfg})
    reports = {}

    def report(name, config):
        r = w.build_report(local, c0, config)
        reports[name] = r
        save(out / 'reports' / f'{name}.json', r)
        return r['freshness']

    assert report('A', [])['status'] == 'UNKNOWN'
    assert report('B', cfg)['status'] == 'LATER_STATE_WITNESSED'
    assert reports['B']['freshness']['steps'] == 2
    # Independent fork, valid shape/address and signed by the configured key.
    fork = w.parse((successor / 'commitments' / f'{c2}.json').read_bytes())
    other_genesis = w.parse((successor / 'commitments' / f'{c0}.json').read_bytes())
    other_genesis['subject']['sha256'] = 'a' * 64
    other_bytes = w.canonical(other_genesis)
    fork['prev'] = w.sha(other_bytes)
    fork['sequence'] = 1
    # Use a separate holder fixture/key so C2 cannot make the control vacuous.
    disconnected = out / 'disconnected'
    save(out / 'fork.json', fork)
    with tempfile.TemporaryDirectory(prefix='wrt012-fork-') as keydir:
        key = Path(keydir) / 'key'
        pub = cli('keygen', '--out', key)['pubkey_hex']
        cli('receive', '--holder-store', disconnected, '--holder-id', 'research-holder', '--key', key,
            '--commitment-file', out / 'fork.json', '--observed', 'experiment-order-only')
    save(disconnected / 'commitments' / f'{w.sha(other_bytes)}.json', other_genesis)
    fork_cfg = [dict(cfg[0], store=str(disconnected), pubkey_hex=pub)]
    assert report('C', fork_cfg)['status'] == 'UNKNOWN'
    assert any(n['outcome'] == 'DISCONNECTED' for n in reports['C']['freshness']['notes'])
    # Remove the intermediate and its own receipt, leaving only the later receipt.
    middle = successor / 'commitments' / f'{c1}.json'
    receipt = successor / 'receipts' / f'{c1}.json'
    middle_bytes, receipt_bytes = middle.read_bytes(), receipt.read_bytes()
    middle.unlink(); receipt.unlink()
    assert report('D', cfg)['status'] == 'UNKNOWN'
    assert any(n['outcome'] == 'PATH_INCOMPLETE' for n in reports['D']['freshness']['notes'])
    middle.write_bytes(b'{}')
    assert report('E', cfg)['status'] == 'UNKNOWN'
    assert any(n['outcome'] == 'LINK_TAMPERED' for n in reports['E']['freshness']['notes'])
    middle.write_bytes(middle_bytes); receipt.write_bytes(receipt_bytes)
    assert report('F', [dict(cfg[0], pubkey_hex='0' * 64)])['status'] == 'UNKNOWN'
    assert all(n['outcome'] == 'RECEIPT_REFUSED' for n in reports['F']['freshness']['notes'])
    old_holder = out / 'old-holder'
    for directory in ('commitments', 'receipts'):
        (old_holder / directory).mkdir(parents=True)
        shutil.copyfile(successor / directory / f'{c0}.json', old_holder / directory / f'{c0}.json')
    assert report('G', [dict(cfg[0], store=str(old_holder))])['status'] == 'UNKNOWN'
    cli('run-verifier', '--store', local, '--commitment', c0,
        '--policy', out / 'policy.json', '--subject', out / 'subject.bin')
    assert report('H', cfg) == reports['B']['freshness']
    assert reports['H']['verification']['result'] == 'PASS'
    assert reports['B']['verification']['result'] == 'NOT_RUN'
    save(out / 'results.json', {'passed': list(reports), 'transport_commit': transport_commit,
         'commitments': commitments, 'independent_custody': 'NOT_DEMONSTRATED',
         'semantic_credit': 'none', 'verification_scope': reports['H']['verification']['scope']})
    print('8/8 endpoints; Git clone byte readback passed; independent custody NOT_DEMONSTRATED')


if __name__ == '__main__':
    main()

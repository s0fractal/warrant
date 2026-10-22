#!/usr/bin/env python3
"""Signed Warrant review/task handoff. Local files only; no code execution from packets.

Receive acknowledges delivery, then files a receiver-owned work duty. Submit is
an ATTESTED candidate, never automatic reviewer acceptance or Sigma replay.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from warrant import engine as E, jcs as C, records as R
from warrant.keys import Key
from warrant.store import Store, Trust

FORMAT = 'warrant-review-handoff/1'
USES = {'continue': {'delivery': ['MATCH_EXPECTED_SET', 'LOCAL_CAPTURE'],
                     'reliance': ['ELIGIBLE'], 'fresh': True},
        'import': {'delivery': ['MATCH_EXPECTED_SET']}}


def need(ok, detail):
    if not ok:
        raise ValueError(detail)


def write(path, doc):
    Path(path).write_bytes(C.canon(doc))


def bounded(path):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024 * 1024,
         'expected regular file <=16MiB')
    return path.read_bytes()


def pinned(path, pin):
    raw = bounded(path)
    need(C.digest(raw) == pin, 'operator pin mismatch; nothing imported')
    return C.loads(raw)


class Party:
    def __init__(self, root, name=None, peers=()):
        self.root = Path(root).resolve()
        if name is None:
            self.doc = C.loads(bounded(self.root / 'config.json'))
            self.name = next(iter(self.doc['workspaces']))
            self.key = Key.from_seed_hex((self.root / 'private.key').read_text())
            self.store = Store(self.root / 'store')
            return
        self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        self.name, self.key = name, Key.generate()
        fd = os.open(self.root / 'private.key', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(self.key.seed_hex())
        self.store = Store(self.root / 'store').init()
        write(self.root / 'profile.json', E.profile(uses={'continue': {'requires_triggers': False}},
                                                   targets=['dependency-audit/68'], providers=[]))
        write(self.root / 'trust.json', Trust.document([(name, self.key.public), *peers]))
        self.doc = {'agent_api': 'warrant-agent/1', 'state': str(self.root / 'state'),
                    'workspaces': {name: {'store': str(self.root / 'store'),
                        'trust': str(self.root / 'trust.json'), 'profile': str(self.root / 'profile.json'),
                        'signer': {'actor': name, 'key': str(self.root / 'private.key')},
                        'source_name': name, 'uses': USES, 'expectations': {}, 'limits': {}}}}
        self.save()

    def save(self):
        write(self.root / 'config.json', self.doc)

    def ok(self, operation, **request):
        p = subprocess.run([str(Path(sys.executable).parent / 'warrant-agent'), '--config',
                            str(self.root / 'config.json'), operation, '-'],
                           input=json.dumps(dict(request, workspace=self.name)), capture_output=True,
                           text=True, cwd=self.root, timeout=120)
        out = json.loads(p.stdout)
        need(p.returncode == 0 and 'ok' in out, str(out))
        return out['ok']

    def file(self, kind, body):
        return self.store.append(kind, self.name, int(time.time()), body, self.key)

    def context(self, duty):
        return self.ok('context', actor=self.name, use='continue', targets=[{'kind': 'duty', 'id': duty}])

    def export(self, duty):
        v = self.context(duty)
        # New export id for each new frozen view; never reuse an old export snapshot.
        return self.ok('handoff', op='export', view_token=v['view_token'],
                       roots=[{'kind': 'duty', 'id': duty}], request_id=v['view_token'])['data']['package']

    def import_(self, pkg, duty, source):
        self.doc['workspaces'][self.name]['expectations']['operator-pin'] = {
            'manifest': C.doc_id(pkg['manifest']), 'source': source, 'exporter': source}
        self.save()
        seen = self.ok('handoff', op='inspect', manifest=pkg['manifest'], payload=pkg['payload'],
                       declaration=pkg['declaration'], expectation='operator-pin', actor=self.name,
                       targets=[{'kind': 'duty', 'id': duty}])
        need(seen['delivery']['relation'] == 'MATCH_EXPECTED_SET', 'incomplete/substituted delivery')
        self.ok('handoff', op='import', staged_id=seen['data']['staged_id'],
                request_id='import-' + C.doc_id(pkg['manifest']))
        snap = self.store.snapshot()
        good, bad = snap.authentic(Trust.load(self.root / 'trust.json'))
        need(not bad and not snap.misfiled, 'unauthenticated records')
        return snap, good

    def accept(self, duty, transition):
        view = self.context(duty)
        req = dict(based_on=view['view_token'], request_id='ack-' + transition,
                   type='accept', body={'transition': transition, 'item': 0})
        draft = self.ok('prepare', **req)['data']
        first = self.ok('commit', draft_id=draft['draft_id'])['data']
        count = len(self.store.snapshot().records)
        again = self.ok('prepare', **req)['data']
        retry = self.ok('commit', draft_id=again['draft_id'])['data']
        need(first['record_id'] == retry['record_id'] and len(self.store.snapshot().records) == count,
             'retry created another acceptance')
        return first['record_id']


def emit(path, doc):
    write(path, doc)
    print(json.dumps({'file': str(path), 'sha256': C.digest(Path(path).read_bytes()),
                      'public': doc['public'], 'duty': doc['duty'], 'stage': doc['stage']}, indent=2))


def produce(a):
    p = Party(a.work, 'codex-review')
    task = C.loads(bounded(a.task))
    for h, filename in task['local_attachments'].items():
        need(p.store.put_blob(bounded(filename)) == h, 'attachment digest mismatch')
    # Paths are producer-side conveniences and must not travel to the receiver.
    public_task = dict(task)
    del public_task['local_attachments']
    task_id = p.store.put_json(public_task)
    d = p.file('duty', R.duty(p.name, 'Deliver exact Sigma #68 review and amendment task ' + task_id,
                            ['claude-68'], {'attest': {}}, accept_by=['claude-68'],
                            subject=task['reviewed_head']))
    evidence = sorted({task_id, *task['attachments'].values()})
    tr = p.file('transition', R.transition('ATTESTED', evidence,
        closes=[R.item(d, 'discharge', evidence)],
        established=['review and task bytes delivered for receiver inspection'],
        residual=['not acknowledgment by receiver', 'not acceptance of an amendment'], subject=task['reviewed_head']))
    packet = {'format': FORMAT, 'stage': 'REVIEW_TASK', 'actor': p.name, 'public': p.key.public,
              'duty': d, 'transition': tr, 'task': task_id, 'package': p.export(d)}
    write(p.root / 'sent.json', packet)
    emit(a.output, packet)


def receive(a):
    packet = pinned(a.packet, a.pin)
    need(packet['format'] == FORMAT and packet['stage'] == 'REVIEW_TASK'
         and packet['actor'] == 'codex-review', 'not the expected review task')
    p = Party(a.work, 'claude-68', [('codex-review', packet['public'])])
    snap, good = p.import_(packet['package'], packet['duty'], packet['actor'])
    tr = good[packet['transition']]['body']
    need(good[packet['duty']]['actor'] == 'codex-review'
         and good[packet['transition']]['actor'] == 'codex-review'
         and packet['task'] in tr['evidence']
         and R.item(packet['duty'], 'discharge', tr['evidence']) in tr['closes'], 'review binding')
    task = snap.json_blob(packet['task'])
    need(task is not None, 'missing task')
    # Hash filenames only: packet bytes never choose filesystem paths or execute code.
    inbox = p.root / 'inbox'
    inbox.mkdir()
    for h in sorted(set(task['attachments'].values()) | {packet['task']}):
        raw = snap.blob(h)
        need(raw is not None, 'missing task attachment')
        (inbox / h).write_bytes(raw)
    acceptance = p.accept(packet['duty'], packet['transition'])
    d = p.file('duty', R.duty(p.name, 'Respond to Sigma #68 amendment task ' + packet['task'],
                            ['codex-review'], {'attest': {}}, accept_by=['codex-review'],
                            requires=[packet['duty']], subject=task['reviewed_head']))
    state = {'packet_sha256': a.pin, 'task': packet['task'], 'producer_duty': packet['duty'],
             'producer_transition': packet['transition'], 'delivery_acceptance': acceptance, 'duty': d}
    write(p.root / 'task-state.json', state)
    reply = {'format': FORMAT, 'stage': 'ACK', 'actor': p.name, 'public': p.key.public,
             **state, 'package': p.export(d)}
    emit(a.output, reply)
    print(json.dumps({'task': task, 'inbox': str(inbox), 'meaning': 'delivery accepted; amendment work OPEN'}, indent=2))


def submit(a):
    p = Party(a.work)
    need(p.name == 'claude-68', 'receiver workspace required')
    state = C.loads(bounded(p.root / 'task-state.json'))
    result = {'task': state['task'], 'packet_sha256': state['packet_sha256'], 'status': a.status,
              'report': p.store.put_blob(bounded(a.report)),
              'artifacts': [p.store.put_blob(bounded(x)) for x in a.artifact]}
    h = p.store.put_json(result)
    ev = sorted({h, result['report'], *result['artifacts']})
    closes = [R.item(state['duty'], 'discharge', ev)] if a.status == 'candidate' else []
    tr = p.file('transition', R.transition('ATTESTED', ev, closes=closes,
        established=['receiver submitted ' + a.status + ' response to exact task'],
        residual=['receiver-reported execution', 'independent review and Codex acceptance pending']))
    emit(a.output, {'format': FORMAT, 'stage': 'SUBMISSION', 'actor': p.name, 'public': p.key.public,
                    **state, 'submission': h, 'transition': tr, 'package': p.export(state['duty'])})


def verify(a):
    reply = pinned(a.packet, a.pin)
    p = Party(a.work)
    sent = C.loads(bounded(p.root / 'sent.json'))
    need(p.name == 'codex-review' and reply['format'] == FORMAT and reply['actor'] == 'claude-68'
         and reply['stage'] in ['ACK', 'SUBMISSION'], 'expected receiver reply')
    need(reply['packet_sha256'] == C.digest(C.canon(sent)) and reply['task'] == sent['task']
         and reply['producer_duty'] == sent['duty']
         and reply['producer_transition'] == sent['transition'], 'reply for another task')
    trust_path = p.root / 'trust.json'
    trust = C.loads(bounded(trust_path))
    old = [k['public'] for k in trust['keys'] if k['actor'] == 'claude-68']
    need(not old or old == [reply['public']], 'receiver key changed; explicit new handoff required')
    if not old:
        trust['keys'].append({'actor': 'claude-68', 'public': reply['public']})
        write(trust_path, trust)
    snap, good = p.import_(reply['package'], reply['duty'], reply['actor'])
    ack = good[reply['delivery_acceptance']]
    need(ack['actor'] == 'claude-68' and ack['type'] == 'accept'
         and ack['body']['transition'] == sent['transition'] and ack['body']['item'] == 0, 'wrong delivery acknowledgment')
    duty = good[reply['duty']]
    need(duty['actor'] == 'claude-68' and duty['type'] == 'duty'
         and duty['body'] == R.duty('claude-68', 'Respond to Sigma #68 amendment task ' + sent['task'],
            ['codex-review'], {'attest': {}}, accept_by=['codex-review'], requires=[sent['duty']],
            subject=good[sent['duty']]['body']['subject']), 'different receiver work duty')
    result = None
    if reply['stage'] == 'SUBMISSION':
        result = snap.json_blob(reply['submission'])
        need(result is not None and result['task'] == sent['task']
             and result['packet_sha256'] == reply['packet_sha256'], 'submission for another task')
        ev = sorted({reply['submission'], result['report'], *result['artifacts']})
        tr = good[reply['transition']]
        expected_closes = [R.item(reply['duty'], 'discharge', ev)] if result['status'] == 'candidate' else []
        need(result['status'] in ['candidate', 'blocked', 'inconclusive'] and tr['actor'] == 'claude-68'
             and tr['type'] == 'transition' and tr['body']['basis'] == 'ATTESTED'
             and tr['body']['evidence'] == ev and tr['body']['closes'] == expected_closes,
             'unsigned or unbound submission claim')
        for h in ev:
            need(snap.blob(h) is not None, 'missing response artifact')
    cap = p.context(reply['duty'])['data']['capsules'][0]
    need(cap['disposition'] != 'DISCHARGED', 'submission silently accepted')
    print(json.dumps({'verified': reply['stage'], 'delivery': 'MATCH_EXPECTED_SET',
                      'task': sent['task'], 'receiver_duty': reply['duty'],
                      'work_disposition': cap['disposition'], 'submission': result,
                      'reviewer_acceptance': 'NOT_GIVEN'}, indent=2))


def update(a):
    """Import a signed review update into the existing receiver-owned workspace."""
    packet = pinned(a.packet, a.pin)
    p = Party(a.work)
    state = C.loads(bounded(p.root / 'task-state.json'))
    need(p.name == 'claude-68' and packet['format'] == FORMAT
         and packet['stage'] == 'REVIEW_UPDATE' and packet['actor'] == 'codex-review'
         and packet['task'] == state['task'] and packet['duty'] == state['producer_duty']
         and packet['packet_sha256'] == state['packet_sha256'], 'update for another handoff')
    trust = C.loads(bounded(p.root / 'trust.json'))
    need(any(k['actor'] == 'codex-review' and k['public'] == packet['public'] for k in trust['keys']),
         'reviewer key changed')
    snap, good = p.import_(packet['package'], packet['duty'], packet['actor'])
    tr = good[packet['transition']]
    doc = snap.json_blob(packet['update'])
    need(tr['type'] == 'transition' and tr['actor'] == 'codex-review'
         and tr['body']['basis'] == 'ATTESTED' and not tr['body']['closes']
         and doc is not None and doc['task'] == state['task']
         and doc['packet_sha256'] == state['packet_sha256'], 'unbound review update')
    evidence = sorted({packet['update'], *doc['attachments'].values()})
    need(tr['body']['evidence'] == evidence, 'unsigned update attachments')
    for h in evidence:
        raw = snap.blob(h)
        need(raw is not None, 'missing update evidence')
        (p.root / 'inbox' / h).write_bytes(raw)
    print(json.dumps({'review_update': doc, 'inbox': str(p.root / 'inbox'),
                      'receiver_duty': state['duty'], 'reviewer_acceptance': 'NOT_GIVEN'}, indent=2))


def conclude(a):
    """Read back the reviewer's exact signed acceptance of a local candidate."""
    packet = pinned(a.packet, a.pin)
    candidate_raw = bounded(a.candidate)
    candidate = C.loads(candidate_raw)
    p = Party(a.work)
    state = C.loads(bounded(p.root / 'task-state.json'))
    need(p.name == 'claude-68' and packet['format'] == FORMAT
         and packet['stage'] == 'REVIEW_ACCEPTANCE' and packet['actor'] == 'codex-review'
         and packet['task'] == state['task'] and packet['duty'] == state['duty']
         and packet['packet_sha256'] == state['packet_sha256']
         and packet['receiver_public'] == p.key.public
         and packet['reply_sha256'] == C.digest(candidate_raw)
         and candidate['public'] == p.key.public and candidate['task'] == state['task']
         and candidate['duty'] == state['duty'] and candidate['stage'] == 'SUBMISSION'
         and candidate['transition'] == packet['accepted_transition'], 'acceptance for another candidate')
    trust = C.loads(bounded(p.root / 'trust.json'))
    need(any(k['actor'] == 'codex-review' and k['public'] == packet['public'] for k in trust['keys']),
         'reviewer key changed')
    snap, good = p.import_(packet['package'], state['duty'], packet['actor'])
    tr = good[packet['accepted_transition']]
    acc = good[packet['acceptance']]
    review = snap.json_blob(packet['review'])
    need(tr['type'] == 'transition' and tr['actor'] == 'claude-68'
         and tr['body']['closes'][0]['duty'] == state['duty']
         and tr['body']['closes'][0]['act'] == 'discharge'
         and acc['type'] == 'accept' and acc['actor'] == 'codex-review'
         and acc['body']['transition'] == candidate['transition'] and acc['body']['item'] == 0
         and acc['body']['evidence'] == tr['body']['closes'][0]['evidence']
         and packet['review'] in acc['body']['support']
         and review is not None and review['verdict'] == 'ACCEPT'
         and review['task'] == state['task'] and review['reply_sha256'] == packet['reply_sha256'],
         'unsigned or unbound acceptance')
    caps = p.context(state['duty'])['data']['capsules']
    cap = next(c for c in caps if c['target'] == state['duty'])
    need(cap['disposition'] == 'DISCHARGED', 'acceptance did not discharge the work duty')
    print(json.dumps({'receiver_duty': state['duty'], 'disposition': cap['disposition'],
                      'acceptance': packet['acceptance'], 'review': review,
                      'private_key_exported': False}, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('mode', choices=['produce', 'receive', 'submit', 'verify', 'update', 'conclude'])
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--task', type=Path)
    ap.add_argument('--packet', type=Path)
    ap.add_argument('--pin')
    ap.add_argument('--output', type=Path)
    ap.add_argument('--candidate', type=Path)
    ap.add_argument('--report', type=Path)
    ap.add_argument('--artifact', type=Path, action='append', default=[])
    ap.add_argument('--status', choices=['candidate', 'blocked', 'inconclusive'], default='candidate')
    args = ap.parse_args()
    try:
        {'produce': produce, 'receive': receive, 'submit': submit, 'verify': verify, 'update': update, 'conclude': conclude}[args.mode](args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'REFUSED', 'detail': str(exc)}), file=sys.stderr)
        sys.exit(2)

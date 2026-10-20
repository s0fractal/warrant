#!/usr/bin/env python3
"""Two local roles; signatures/delivery tests, not remote execution evidence."""
import copy
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from warrant import jcs as C
import run as H

RUN = Path(__file__).with_name('run.py')


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        def call(mode, *args, ok=True):
            out = subprocess.run([sys.executable, str(RUN), mode, *map(str, args)],
                                 text=True, capture_output=True)
            assert (out.returncode == 0) == ok, out.stdout + out.stderr
            return out
        report = root/'review.md'; report.write_text('Synthetic review fixture')
        h = C.digest(report.read_bytes())
        task = root/'task.json'
        task.write_bytes(C.canon({'reviewed_head': 'ac' * 20, 'attachments': {'review': h},
                                 'local_attachments': {h: str(report)}}))
        packet, ack, reply = [root/n for n in ['packet.json','ack.json','reply.json']]
        sender, receiver = root/'sender',root/'receiver'
        call('produce','--work',sender,'--task',task,'--output',packet)
        pin = C.digest(packet.read_bytes())
        # Wrong operator pin refuses before creating a receiver key/store.
        call('receive','--work',root/'bad','--packet',packet,'--pin','00'*32,'--output',ack,ok=False)
        assert not (root/'bad').exists()
        call('receive','--work',receiver,'--packet',packet,'--pin',pin,'--output',ack)
        assert (receiver/'private.key').stat().st_mode & 0o777 == 0o600
        call('verify','--work',sender,'--packet',ack,'--pin',C.digest(ack.read_bytes()))
        # Review updates reuse the established reviewer key and receiver work duty.
        producer = H.Party(sender)
        sent = C.loads(packet.read_bytes())
        update_doc = {'task': sent['task'], 'packet_sha256': pin, 'attachments': {'review': h},
                      'verdict': 'AMEND'}
        update_id = producer.store.put_json(update_doc)
        evidence = sorted({update_id, h})
        transition = producer.file('transition', H.R.transition('ATTESTED', evidence,
                                    established=['synthetic review update']))
        update_packet = {'format': H.FORMAT, 'stage': 'REVIEW_UPDATE', 'actor': 'codex-review',
                         'public': producer.key.public, 'task': sent['task'], 'packet_sha256': pin,
                         'duty': sent['duty'], 'update': update_id, 'transition': transition,
                         'package': producer.export(sent['duty'])}
        update_file = root/'update.json'; update_file.write_bytes(C.canon(update_packet))
        state_before = (receiver/'task-state.json').read_bytes()
        call('update','--work',receiver,'--packet',update_file,'--pin',C.digest(update_file.read_bytes()))
        assert (receiver/'task-state.json').read_bytes() == state_before
        wrong_update = copy.deepcopy(update_packet); wrong_update['public'] = '00'*32
        update_file.write_bytes(C.canon(wrong_update))
        call('update','--work',receiver,'--packet',update_file,'--pin',C.digest(update_file.read_bytes()),ok=False)
        wrong_update = copy.deepcopy(update_packet); wrong_update['task'] = '00'*32
        update_file.write_bytes(C.canon(wrong_update))
        call('update','--work',receiver,'--packet',update_file,'--pin',C.digest(update_file.read_bytes()),ok=False)
        submitted = root/'submission.md';submitted.write_text('Synthetic candidate, no real amendment')
        call('submit','--work',receiver,'--report',submitted,'--output',reply)
        checked = call('verify','--work',sender,'--packet',reply,'--pin',C.digest(reply.read_bytes()))
        assert json.loads(checked.stdout)['reviewer_acceptance'] == 'NOT_GIVEN'
        original = C.loads(reply.read_bytes())
        # Even a freshly operator-pinned outer reply cannot redirect the task.
        wrong = copy.deepcopy(original); wrong['task']='00'*32
        changed=root/'changed.json';changed.write_bytes(C.canon(wrong))
        call('verify','--work',sender,'--packet',changed,'--pin',C.digest(changed.read_bytes()),ok=False)
        # Substituting signed result metadata cannot reuse the signed transition.
        wrong = copy.deepcopy(original); wrong['submission']=h
        changed.write_bytes(C.canon(wrong))
        call('verify','--work',sender,'--packet',changed,'--pin',C.digest(changed.read_bytes()),ok=False)
        # Corrupt transport: API must refuse missing declared bytes.
        wrong = C.loads(packet.read_bytes()); wrong['package']['payload']['blobs'].pop()
        changed.write_bytes(C.canon(wrong))
        call('receive','--work',root/'damaged','--packet',changed,'--pin',C.digest(changed.read_bytes()),'--output',root/'bad-ack',ok=False)
        # Blocked/inconclusive responses never submit a discharge item.
        for status in ['blocked','inconclusive']:
            call('submit','--work',receiver,'--report',submitted,'--status',status,'--output',reply)
            out=call('verify','--work',sender,'--packet',reply,'--pin',C.digest(reply.read_bytes()))
            assert json.loads(out.stdout)['work_disposition'] != 'DISCHARGED'
        # Only an explicit reviewer acceptance of the exact candidate closes work.
        candidate_file = root/'candidate-original.json'
        candidate_file.write_bytes(C.canon(original))
        candidate_pin = C.digest(candidate_file.read_bytes())
        review = producer.store.put_json({'verdict': 'ACCEPT', 'task': sent['task'],
                                         'reply_sha256': candidate_pin})
        context = producer.context(original['duty'])
        request = dict(based_on=context['view_token'], request_id='explicit-review-accept', type='accept',
                       body={'transition': original['transition'], 'item': 0, 'support': [review]})
        draft = producer.ok('prepare', **request)['data']
        acceptance = producer.ok('commit', draft_id=draft['draft_id'])['data']['record_id']
        closing = {'format': H.FORMAT, 'stage': 'REVIEW_ACCEPTANCE', 'actor': 'codex-review',
                   'public': producer.key.public, 'receiver_public': original['public'],
                   'task': sent['task'], 'packet_sha256': pin, 'duty': original['duty'],
                   'reply_sha256': candidate_pin, 'accepted_transition': original['transition'],
                   'acceptance': acceptance, 'review': review, 'package': producer.export(original['duty'])}
        closing_file = root/'acceptance.json'; closing_file.write_bytes(C.canon(closing))
        closing_pin = C.digest(closing_file.read_bytes())
        # Another public response from the same receiver cannot inherit acceptance.
        call('conclude','--work',receiver,'--packet',closing_file,'--pin',closing_pin,
             '--candidate',reply,ok=False)
        out = call('conclude','--work',receiver,'--packet',closing_file,'--pin',closing_pin,
                   '--candidate',candidate_file)
        assert json.loads(out.stdout)['disposition'] == 'DISCHARGED'
        out2 = call('conclude','--work',receiver,'--packet',closing_file,'--pin',closing_pin,
                    '--candidate',candidate_file)
        assert json.loads(out2.stdout)['acceptance'] == acceptance
        # Neither a private signing seed nor a producer-local task path is exported.
        wire = b''.join(base64.b64decode(item['bytes_base64'], validate=True)
                        for file in [packet, ack, reply]
                        for group in C.loads(file.read_bytes())['package']['payload'].values()
                        for item in group)
        assert str(report).encode() not in wire
        for party in [sender,receiver]:
            assert (party/'private.key').read_bytes() not in wire
        print('REVIEW-HANDOFF: local roundtrip PASS; wrong pin/task/submission/missing bytes refused; '
              'fresh-process retry stable; work stays open until exact explicit acceptance; blocked/inconclusive stay open; signed updates retain duty and refuse wrong task/key; no keys exported')


if __name__ == '__main__':
    main()

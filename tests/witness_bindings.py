"""Regression controls for independent review F1-F6. Offline, temporary stores only."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]/'tools/witness.py'
spec=importlib.util.spec_from_file_location('w',TOOL)
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class Bindings(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.d=Path(self.tmp.name);self.st=self.d/'store'
        self.subject=self.d/'subject';self.subject.write_bytes(b'BAD')
        self.policy=self.d/'policy'
        self.policy.write_bytes(w.canonical({'type':w.BYTE_PROFILE,'checker_sha256':w.checker_sha256(),'expected_sha256':w.sha(b'BAD')}))
        rc,out=self.cli('commit','--store',self.st,'--subject-kind','file','--subject-sha256',w.sha(b'BAD'),'--verifier-closure-sha256',w.sha(self.policy.read_bytes()),'--stream','a'*64)
        self.assertEqual(rc,0);self.c=out['commitment']

    def cli(self,*args):
        output=io.StringIO()
        with contextlib.redirect_stdout(output): rc=w.main(list(map(str,args)))
        return rc,json.loads(output.getvalue())

    def run_check(self):
        return self.cli('run-verifier','--store',self.st,'--commitment',self.c,'--policy',self.policy,'--subject',self.subject)

    def test_F1_fabricated_legacy_claim_is_not_pass(self):
        rec={'type':w.RUN_TYPE,'commitment':self.c,'closure_sha256':w.sha(self.policy.read_bytes()),'method':'EXTERNAL_CLOSURE','result':'PASS','scope':'forged'}
        w.write_new(self.st/'runs'/f'{self.c}.json',w.canonical(rec))
        self.assertEqual(w.build_report(self.st,self.c,[])['verification']['result'],'NOT_RUN')

    def test_F1_replay_rejects_false_result(self):
        self.assertEqual(self.run_check()[0],0)
        rp=self.st/'runs'/f'{self.c}.json';r=w.parse(rp.read_bytes());r['verification']['result']='FAIL';rp.write_bytes(w.canonical(r))
        with self.assertRaisesRegex(w.Refused,'RUN_RESULT_DIVERGED'): w.build_report(self.st,self.c,[])

    def test_F2_wrong_subject_refused_before_writes(self):
        self.subject.write_bytes(b'GOOD')
        rc,r=self.run_check();self.assertEqual((rc,r.get('reason')),(2,'SUBJECT_PIN'))
        self.assertFalse((self.st/'runs').exists());self.assertFalse((self.st/'operands').exists())

    def test_F3_no_supplied_python_executed(self):
        script=self.d/'bad.py';script.write_text("raise Exception('untrusted code')\n")
        with patch.object(w.subprocess,'run',side_effect=AssertionError('must not launch')):
            rc,r=self.cli('run-verifier','--store',self.st,'--commitment',self.c,'--script',script)
        self.assertEqual((rc,r.get('reason')),(2,'UNBOUND_EXECUTION_UNSUPPORTED'))
        self.assertFalse((self.st/'runs').exists())

    def test_F3_changed_checker_refused_on_replay(self):
        self.assertEqual(self.run_check()[0],0)
        with patch.object(w,'checker_sha256',return_value='0'*64):
            with self.assertRaisesRegex(w.Refused,'CHECKER_CHANGED'): w.build_report(self.st,self.c,[])

    def test_F4_repeat_does_not_publish_operands_again(self):
        self.assertEqual(self.run_check()[0],0)
        with patch.object(w,'put_operand',side_effect=AssertionError('duplicate write')):
            rc,r=self.run_check()
        self.assertEqual((rc,r.get('reason')),(2,'RUN_EXISTS_NEVER_OVERWRITE'))

    def test_interruption_is_not_a_success(self):
        with patch.object(w,'put_operand',side_effect=OSError('injected interruption')):
            self.assertEqual(self.run_check()[0],2)
        r=w.build_report(self.st,self.c,[])['verification']
        self.assertEqual((r['result'],r['note']),('NOT_RUN','RUN_INCOMPLETE'))
        self.assertEqual(self.run_check()[1]['reason'],'RUN_EXISTS_NEVER_OVERWRITE')

    def test_operand_tampering_is_refused(self):
        self.assertEqual(self.run_check()[0],0)
        (self.st/'operands'/f'{w.sha(b"BAD")}.bin').write_bytes(b'GOOD')
        with self.assertRaisesRegex(w.Refused,'OPERAND_PIN'): w.build_report(self.st,self.c,[])

    def test_F5_signed_holder_must_match_config(self):
        key=self.d/'key';rc,pub=self.cli('keygen','--out',key);self.assertEqual(rc,0)
        hs=self.d/'holder';rc,_=self.cli('receive','--holder-store',hs,'--holder-id','actual-A','--key',key,'--commitment-file',self.st/'commitments'/f'{self.c}.json','--observed','2026-09-10');self.assertEqual(rc,0)
        h={'id':'actual-A','pubkey_hex':pub['pubkey_hex'],'store':str(hs),'custody':'same-host'}
        self.assertEqual(w.build_report(self.st,self.c,[h])['holding'][0]['status'],'EXTERNALLY_OBSERVED')
        h['id']='configured-B';r=w.build_report(self.st,self.c,[h])
        self.assertEqual(r['holding'][0]['status'],'NONE')
        self.assertEqual(r['freshness']['notes'][0]['why'],'RECEIPT_HOLDER')

    def test_F6_exact_config_bytes_and_limits_recorded(self):
        cfg=self.d/'config';cfg.write_text('{"holders": []}\n')
        rc,r=self.cli('report','--store',self.st,'--commitment',self.c,'--holders',cfg,'--max-path',10)
        self.assertEqual(rc,0);self.assertEqual(r['inputs_sha256'][str(cfg)],w.sha(cfg.read_bytes()))
        self.assertEqual(r['evaluation']['max_path_steps'],10)
        self.assertEqual(r['evaluation']['tool_sha256'],w.checker_sha256())
        cfg.write_text('{"holders":[]}')
        rc,r2=self.cli('report','--store',self.st,'--commitment',self.c,'--holders',cfg)
        self.assertNotEqual(r['holder_config_sha256'],r2['holder_config_sha256'])
        self.assertEqual(r['evaluation']['holders_value_sha256'],r2['evaluation']['holders_value_sha256'])


if __name__=='__main__': unittest.main()

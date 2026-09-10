"""Offline repair demonstration. Writes only to a NEW output directory."""
import argparse,contextlib,hashlib,importlib.util,io,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('w',ROOT/'tools/witness.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
d=Path(a.output).resolve();d.mkdir(parents=True,exist_ok=False)
def write(name,obj): (d/name).write_bytes(w.canonical(obj))
def cli(*args):
 out=io.StringIO()
 with contextlib.redirect_stdout(out): rc=w.main(list(map(str,args)))
 return rc,json.loads(out.getvalue())
write('protocol.json',{'tool_sha256':w.checker_sha256(),'driver_sha256':w.sha(Path(__file__).read_bytes()),'network_calls':0,'profile':w.BYTE_PROFILE,'endpoints':['legacy run not trusted','byte check replay passes','false result refused','wrong operand refused']})
legacy=ROOT/'experiments/wrt-012-e2e-001/store'
c=next((legacy/'runs').glob('*.json')).stem
old=w.build_report(legacy,c,[])['verification'];assert old['result']=='NOT_RUN'
(d/'subject').write_bytes(b'bounded-byte-check\n')
write('policy.json',{'type':w.BYTE_PROFILE,'checker_sha256':w.checker_sha256(),'expected_sha256':w.sha((d/'subject').read_bytes())})
st=d/'store';rc,r=cli('commit','--store',st,'--subject-kind','file','--subject-sha256',w.sha((d/'subject').read_bytes()),'--verifier-closure-sha256',w.sha((d/'policy.json').read_bytes()),'--stream','7'*64);assert rc==0
c=r['commitment'];write('holders.json',{'holders':[]})
rc,r=cli('run-verifier','--store',st,'--commitment',c,'--subject',d/'subject','--policy',d/'policy.json');assert rc==0 and r['result']=='PASS'
rc,report=cli('report','--store',st,'--commitment',c,'--holders',d/'holders.json');assert rc==0 and report['verification']['result']=='PASS';write('report.json',report)
rp=st/'runs'/f'{c}.json';original=rp.read_bytes();rec=w.parse(original);rec['verification']['result']='FAIL';rp.write_bytes(w.canonical(rec))
rc,bad=cli('report','--store',st,'--commitment',c,'--holders',d/'holders.json');assert rc==2 and bad['reason']=='RUN_RESULT_DIVERGED';rp.write_bytes(original)
(d/'wrong').write_bytes(b'different')
rc,wrong=cli('run-verifier','--store',st,'--commitment',c,'--subject',d/'wrong','--policy',d/'policy.json');assert rc==2 and wrong['reason']=='SUBJECT_PIN'
write('results.json',{'legacy_verification':old,'replayed_verification':report['verification'],'false_result':bad,'wrong_subject':wrong,'external_witness':'NOT_DEMONSTRATED','historical_execution':'NOT_ATTESTED','network_calls':0})
print('4/4 repair endpoints, no network calls')

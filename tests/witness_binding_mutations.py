"""Fresh regression mutations: failure must be an assertion, not a crashing harness."""
import shutil,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MUTATIONS=[
 ('subject', 'need(sha(subject_bytes) == obj["subject"]["sha256"], "SUBJECT_PIN")',
  'pass', 'test_F2_wrong_subject_refused_before_writes'),
 ('result', 'need(canonical(ver) == canonical(run["verification"]), "RUN_RESULT_DIVERGED")',
  'pass', 'test_F1_replay_rejects_false_result'),
 ('holder', 'need(rec["holder"] == h["id"], "RECEIPT_HOLDER")',
  'pass', 'test_F5_signed_holder_must_match_config'),
 ('config', 'rep["inputs_sha256"][str(Path(a.holders))] = sha(config_bytes)',
  'rep["inputs_sha256"][str(Path(a.holders))] = "0" * 64', 'test_F6_exact_config_bytes_and_limits_recorded'),
]
for label,needle,replacement,test in MUTATIONS:
 with tempfile.TemporaryDirectory() as td:
  p=Path(td);(p/'tools').mkdir();(p/'tests').mkdir()
  source=(ROOT/'tools/witness.py').read_text();assert source.count(needle)==1
  (p/'tools/witness.py').write_text(source.replace(needle,replacement))
  shutil.copyfile(ROOT/'tests/witness_bindings.py',p/'tests/witness_bindings.py')
  r=subprocess.run([sys.executable,'-B',str(p/'tests/witness_bindings.py'),'Bindings.'+test],capture_output=True,text=True,timeout=15)
  assert r.returncode==1 and 'FAIL:' in r.stderr and 'ERROR:' not in r.stderr,r.stderr
  print('DETECTED',label,test)
print('4/4 regression mutations detected by assertions')

#!/usr/bin/env python3
"""Read exact active repository objects used by WRT-024; no checkout mutation/network.

python3 collect.py --warrant PATH --sigma PATH --primitives PATH --out DIRECTORY
Requires Python 3.11+. Object IDs are the research slice, not automatically-followed branch names.
"""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

W = 'de0fc912fdfb0bf519a1b0fefca137c13120e354'
S = 'c864d3ee01a2fe46c528bd6e9552438e64df5f6b'
P = '040d1a777310c8819ad861d38f6fd7f9ef5beb48'
C = '71514c04a3c96cc49633d8b239f9d82183dcb897'
FILES = {
 'W': '''AGENTS.md SPEC.md pyproject.toml impl-rs/Cargo.toml impl-rs/src/ski.rs impl/warrant.py impl/sigma_glyph_v05.py impl/sigma_glyph_v06.py trust/ski-runtime-evaluators.json trust/sigma-glyph-anchor-trust.json .github/workflows/ci.yml .github/workflows/wrt-005.yml .github/workflows/x1-cross-repo.yml .github/workflows/publish.yml tools/x1_cross_repo.sh tools/x1_negative_control.sh tools/book1_coverage.py tools/vendor_primitives.py tests/primitives_pack.py third_party/primitives/PIN.json demos/redesign-refund/vendor/sigma/PIN.json proposals/WRT-006-ski-v1-implementation-substitution.md proposals/WRT-007-per-tag-evaluator-dependency.md proposals/WRT-022-authority-falsifiers-crossings.md'''.split(),
 'S': '''AGENTS.md pyproject.toml impl/sigma_glyph.py impl/sigma_resume.py impl/sigma_federation.py spec/ANCHORS.txt .github/workflows/ci.yml .github/workflows/x1-cross-repo.yml .github/workflows/publish.yml .github/workflows/candidate-artifact.yml tools/x1_cross_repo.sh tools/x1_negative_control.sh tools/book1_coverage.py tools/test-all.sh tools/read_warrant_pin.sh tools/warrant_gate.py tools/anchor_governance.py tools/verify_anchors.py tools/candidate_artifact.py tools/candidate_install_check.py tools/evidence_view.py tests/spec_conformance/vectors.json'''.split(),
 'P': '''README.md catalog.json run.py MANIFEST.sha256 .github/workflows/ci.yml tools/import_warrant.py tools/check.py'''.split(),
 'C2': '''pyproject.toml impl/loops.py impl/replay.py impl/replay_sigma_worker.py impl/sigma_resume_c864d3e/PIN.json impl/sigma_resume_c864d3e/sigma_glyph.py impl/sigma_resume_c864d3e/sigma_resume.py'''.split(),
}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('warrant','sigma','primitives','out'): ap.add_argument('--'+name,required=True)
    a=ap.parse_args()
    roots={'W':a.warrant,'S':a.sigma,'P':a.primitives,'C2':a.warrant}
    revs={'W':W,'S':S,'P':P,'C2':C}
    repos={'W':'warrant','S':'sigma-glyph','P':'primitives','C2':'warrant'}
    cache={}; entries=[]
    for symbol, paths in FILES.items():
        for path in paths:
            data=subprocess.run(['git','-C',roots[symbol],'show',f'{revs[symbol]}:{path}'],capture_output=True,check=True).stdout
            cache[symbol,path]=data
            entries.append({'slice':symbol,'repository':repos[symbol],'commit':revs[symbol],'path':path,
                            'sha256':hashlib.sha256(data).hexdigest(),
                            'availability':'local-unpublished' if symbol=='C2' else 'remote-master-snapshot',
                            'git_object':f'{revs[symbol]}:{path}',
                            'source_url':None if symbol=='C2' else f'https://github.com/s0fractal/{repos[symbol]}/blob/{revs[symbol]}/{path}'})
    mirrors=['tools/x1_cross_repo.sh','tools/x1_negative_control.sh','tools/book1_coverage.py','.github/workflows/x1-cross-repo.yml']
    import tomllib
    sm=tomllib.loads(cache['S','pyproject.toml'].decode())
    wm=tomllib.loads(cache['W','pyproject.toml'].decode())
    pack=json.loads(cache['W','third_party/primitives/PIN.json'])
    obs={'mirrors_equal':{p:cache['W',p]==cache['S',p] for p in mirrors},
         'warrant_v06_equals_sigma_head_glyph':cache['W','impl/sigma_glyph_v06.py']==cache['S','impl/sigma_glyph.py'],
         's2_vendor_equals_sigma':{p:cache['C2',f'impl/sigma_resume_c864d3e/{p}']==cache['S',f'impl/{p}'] for p in ('sigma_glyph.py','sigma_resume.py')},
         'sigma_modules':sm['tool']['setuptools']['py-modules'],'sigma_dependencies':sm['project']['dependencies'],
         'warrant_modules':wm['tool']['setuptools']['py-modules'],'warrant_dependencies':wm['project']['dependencies'],
         'warrant_primitives_pin':pack,
         'primitives_class_names':list(json.loads(cache['P','catalog.json'])['classes']),
         'note':'Source inspection only; no public package download or wheel execution claimed.'}
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    (out/'SOURCE-INDEX.json').write_text(json.dumps({'research_date':'2026-10-18','sources':entries},indent=2)+'\n')
    (out/'OBSERVATIONS.json').write_text(json.dumps(obs,indent=2)+'\n')
    print(json.dumps({'source_files':len(entries),'mirrors':obs['mirrors_equal'],'sigma_resume_packaged':'sigma_resume' in obs['sigma_modules'],'candidate_vendor_matches_source':obs['s2_vendor_equals_sigma']},indent=2))

if __name__=='__main__': main()

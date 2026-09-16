"""Read-only Zenodo retention experiment. Does not establish holder receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import urllib.error

RECORD = 22172098
FILE = 'the-reason-runs-again.pdf'
EXPECTED = 'da2f5506e315cb2243eac2700dc7898c2b52930f667963304e0db7904b13a111'
LIMIT = 16 * 1024 * 1024
BASE = f'https://zenodo.org/api/records/{RECORD}'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def classify(metadata, data, expected):
    """Caller supplies a pinned expected digest; metadata is not an authority."""
    if not isinstance(metadata, dict) or metadata.get('id') != RECORD:
        return {'status': 'REFUSED', 'reason': 'RECORD_ID'}
    files = metadata.get('files')
    if not isinstance(files, list) or sum(isinstance(f, dict) and f.get('key') == FILE for f in files) != 1:
        return {'status': 'REFUSED', 'reason': 'FILE_LIST'}
    if len(data) > LIMIT:
        return {'status': 'REFUSED', 'reason': 'SIZE_LIMIT'}
    if sha(data) != expected:
        return {'status': 'REFUSED', 'reason': 'SUBJECT_PIN'}
    return {'status': 'DEPOSIT_BYTES_OBSERVED', 'record': RECORD, 'file': FILE,
            'sha256': sha(data), 'bytes': len(data), 'holder_receipt': 'NONE',
            'freshness': 'UNKNOWN', 'time_verified': False, 'authority': 'none',
            'scope': 'bytes returned by pinned Zenodo record endpoint match caller SHA-256'}


def fetch(url):
    # URLs are closed constants; remote metadata links are deliberately not followed.
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('SIZE_LIMIT')
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    protocol = {'record': RECORD, 'file': FILE, 'expected_sha256': EXPECTED,
                'driver_sha256': sha(Path(__file__).read_bytes()),
                'endpoints': ['actual subject matches', 'wrong subject refused',
                              'wrong record refused', 'missing file refused',
                              'duplicate file refused', 'size limit refuses'],
                'publication_calls': 0, 'new_commitment_retained': 'NOT_DEMONSTRATED'}
    (a.output / 'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n')
    try:
        metadata_bytes = fetch(BASE)
        metadata = json.loads(metadata_bytes)
        data = fetch(f'{BASE}/files/{FILE}/content')
    except (OSError, urllib.error.URLError, ValueError) as error:
        failure = {'status': 'NOT_OBSERVED', 'reason': type(error).__name__,
                   'freshness': 'UNKNOWN', 'new_commitment_retained': 'NOT_DEMONSTRATED'}
        (a.output / 'results.json').write_text(json.dumps(failure, indent=2)+'\n')
        print(json.dumps(failure))
        return 1
    (a.output / 'record.json').write_bytes(metadata_bytes)
    result = classify(metadata, data, EXPECTED)
    assert result['status'] == 'DEPOSIT_BYTES_OBSERVED', result
    controls = {
        'wrong_subject': classify(metadata, data + b'x', EXPECTED),
        'wrong_record': classify(dict(metadata, id=0), data, EXPECTED),
        'missing_file': classify(dict(metadata, files=[]), data, EXPECTED),
        'duplicate_file': classify(dict(metadata, files=[{'key': FILE}]*2), data, EXPECTED),
        'size_limit': classify(metadata, b'x' * (LIMIT+1), EXPECTED),
    }
    assert [r['reason'] for r in controls.values()] == ['SUBJECT_PIN','RECORD_ID','FILE_LIST','FILE_LIST','SIZE_LIMIT']
    (a.output / 'results.json').write_text(json.dumps({'observation': result, 'controls': controls,
        'metadata_sha256': sha(metadata_bytes), 'download_url': f'{BASE}/files/{FILE}/content',
        'new_commitment_retained': 'NOT_DEMONSTRATED'}, indent=2)+'\n')
    print('6/6 endpoints; existing deposited subject observed; no new commitment or holder receipt')


if __name__ == '__main__':
    raise SystemExit(main())

import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('deposit', Path(__file__).with_name('readback.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class ReadbackTests(unittest.TestCase):
    def test_positive_and_negative_pins(self):
        data = b'fixed bytes'
        meta = {'id': d.RECORD, 'files': [{'key': d.FILE}]}
        result = d.classify(meta, data, d.sha(data))
        self.assertEqual(result['status'], 'DEPOSIT_BYTES_OBSERVED')
        self.assertEqual(result['holder_receipt'], 'NONE')
        self.assertEqual(result['freshness'], 'UNKNOWN')
        self.assertEqual(d.classify(meta, b'changed', d.sha(data))['reason'], 'SUBJECT_PIN')
        self.assertEqual(d.classify(dict(meta, id=0), data, d.sha(data))['reason'], 'RECORD_ID')
        for files in ([], None, [{'key': d.FILE}]*2):
            self.assertEqual(d.classify(dict(meta, files=files), data, d.sha(data))['reason'], 'FILE_LIST')
        self.assertEqual(d.classify(meta, b'x'*(d.LIMIT+1), d.sha(data))['reason'], 'SIZE_LIMIT')

    def test_metadata_checksum_cannot_override_bytes(self):
        meta = {'id': d.RECORD, 'files': [{'key': d.FILE, 'checksum': 'sha256:'+d.sha(b'expected')} ]}
        self.assertEqual(d.classify(meta, b'wrong', d.sha(b'expected'))['reason'], 'SUBJECT_PIN')


if __name__ == '__main__':
    unittest.main()

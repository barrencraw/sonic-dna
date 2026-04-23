import unittest
import io
import sys
from utils.dna_ui import main as run_batch
import os
import shutil
import tempfile

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        os.makedirs(self.raw_dir)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.rules_dir)
        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
             import json
             json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 127, "pad": 3},
                    "unknown": {"description": "unknown", "min": 0, "max": 99, "pad": 2},
                    "more": {"description": "more", "min": 0, "max": 99, "pad": 2},
                    "extra": {"description": "extra", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_correlation_id_consistency(self):
        captured_output = io.StringIO()
        sys.stdout = captured_output
        try:
            run_batch(project_root=self.test_dir)
        finally:
            sys.stdout = sys.__stdout__

        lines = captured_output.getvalue().strip().split('\n')
        self.assertTrue(len(lines) > 2)

        correlation_ids = []
        for line in lines:
            if 'correlation_id=' in line:
                cid = line.split('correlation_id=')[1].strip()
                correlation_ids.append(cid)

        self.assertTrue(len(correlation_ids) > 0)
        # All lines should have the same correlation ID
        self.assertEqual(len(set(correlation_ids)), 1, f"Multiple correlation IDs found: {set(correlation_ids)}")

if __name__ == '__main__':
    unittest.main()

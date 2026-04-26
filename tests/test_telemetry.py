import unittest
import os
import shutil
import tempfile
import json
import sys
import io
from utils.dna_ui import main as run_batch

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_batch_correlation_id(self):
        """Verify that all logs in a single batch share the same correlation_id."""
        captured_output = io.StringIO()
        sys.stdout = captured_output

        run_batch(project_root=self.test_dir)

        sys.stdout = sys.__stdout__
        logs = captured_output.getvalue().strip().split('\n')

        telemetry_logs = [line for line in logs if line.startswith("| TELEMETRY | ")]
        self.assertGreater(len(telemetry_logs), 2) # start, process, end at least

        correlation_ids = []
        for log in telemetry_logs:
            json_part = log.replace("| TELEMETRY | ", "")
            data = json.loads(json_part)
            correlation_ids.append(data.get("correlation_id"))

        # All correlation IDs should be the same and not "N/A"
        self.assertEqual(len(set(correlation_ids)), 1)
        self.assertNotEqual(correlation_ids[0], "N/A")
        self.assertTrue(len(correlation_ids[0]) > 0)

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_logs(self):
        f = io.StringIO()
        correlation_id = "test-cid-123"
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        logs = []
        for line in output.splitlines():
            if line.startswith("JSON_LOG: "):
                logs.append(json.loads(line[len("JSON_LOG: "):]))

        self.assertTrue(len(logs) >= 3, f"Expected at least 3 logs, got {len(logs)}")

        # Check mandatory fields in all logs
        for log in logs:
            self.assertEqual(log['correlation_id'], correlation_id)
            self.assertIn('timestamp', log)
            self.assertIn('step', log)
            self.assertIn('outcome', log)

        # Check specific steps
        steps = [log['step'] for log in logs]
        self.assertIn('batch_start', steps)
        self.assertIn('sequence_process', steps)
        self.assertIn('batch_complete', steps)

if __name__ == '__main__':
    unittest.main()

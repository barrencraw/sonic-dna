import unittest
import os
import shutil
import tempfile
import json
import io
import sys
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
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

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
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

    def test_structured_logging(self):
        """Verify that batch processing emits correctly formatted JSON_LOG: telemetry."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]

        self.assertTrue(len(logs) >= 3, f"Expected at least 3 logs (start, item, end), got {len(logs)}")

        # Parse first log (start)
        start_log = json.loads(logs[0].replace('JSON_LOG:', ''))
        self.assertEqual(start_log['correlation_id'], "test-id")
        self.assertEqual(start_log['actor_id'], "test-actor")
        self.assertEqual(start_log['step'], "start")

        # Parse item log
        item_log = json.loads(logs[1].replace('JSON_LOG:', ''))
        self.assertEqual(item_log['correlation_id'], "test-id")
        self.assertEqual(item_log['idempotency_key'], "V100")
        self.assertEqual(item_log['outcome'], "success")
        self.assertIn('latency_ms', item_log)

    def test_naming_alignment(self):
        """Verify that dna_sequence is used as the canonical name in outputs."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

if __name__ == '__main__':
    unittest.main()

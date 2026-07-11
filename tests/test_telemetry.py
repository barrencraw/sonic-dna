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
                "subvars": {"level": {"description": "volume", "min": 0, "max": 999, "pad": 3}}
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_structured_logs(self):
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertTrue(len(logs) >= 3) # start, process_item, end

        # Verify first log
        first_log = json.loads(logs[0][9:])
        self.assertEqual(first_log['correlation_id'], "test-cid")
        self.assertEqual(first_log['actor_id'], "test-actor")
        self.assertEqual(first_log['step'], "start")
        self.assertIn("T", first_log['timestamp'])
        self.assertIn("Z", first_log['timestamp'])

        # Verify item log
        item_log = json.loads(logs[1][9:])
        self.assertEqual(item_log['step'], "process_item")
        self.assertEqual(item_log['outcome'], "success")
        self.assertEqual(item_log['idempotency_key'], "V100")

if __name__ == '__main__':
    unittest.main()

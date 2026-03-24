import unittest
import json
import io
from unittest.mock import patch
from utils.dna_ui import main as run_batch
import os
import shutil
import tempfile

class TestObservability(unittest.TestCase):
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
                    "level": {"description": "volume", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs(self):
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            run_batch(correlation_id="test-corr", actor_id="test-actor")
            output = fake_out.getvalue()

        logs = []
        for line in output.splitlines():
            if line.startswith("[OBSERVABILITY]"):
                logs.append(json.loads(line[len("[OBSERVABILITY] "):]))

        self.assertTrue(len(logs) >= 3, f"Expected at least 3 logs, got {len(logs)}")

        # Start batch log
        self.assertEqual(logs[0]['step'], 'start_batch')
        self.assertEqual(logs[0]['correlation_id'], 'test-corr')
        self.assertEqual(logs[0]['actor_id'], 'test-actor')

        # Process DNA log
        process_log = next(l for l in logs if l['step'] == 'process_dna')
        self.assertEqual(process_log['outcome'], 'SUCCESS')
        self.assertEqual(process_log['idempotency_key'], 'V100')
        self.assertIn('latency_ms', process_log)

        # Complete batch log
        complete_log = logs[-1]
        self.assertEqual(complete_log['step'], 'complete_batch')
        self.assertEqual(complete_log['outcome'], 'SUCCESS')
        self.assertIn('latency_ms', complete_log)

if __name__ == '__main__':
    unittest.main()

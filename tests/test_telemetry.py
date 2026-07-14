import json
import os
import shutil
import tempfile
import unittest
from utils.dna_ui import run_batch

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

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
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
        from unittest.mock import patch
        import io
        from contextlib import redirect_stdout

        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]

        self.assertGreaterEqual(len(log_lines), 3) # batch_start, item_processed, batch_end

        parsed_logs = [json.loads(line[9:]) for line in log_lines]

        # Verify batch_start
        self.assertEqual(parsed_logs[0]['step'], 'batch_start')
        self.assertEqual(parsed_logs[0]['correlation_id'], 'test-cid')
        self.assertIn('timestamp', parsed_logs[0])
        self.assertTrue(parsed_logs[0]['timestamp'].endswith('Z'))

        # Verify item_processed
        item_log = next(log for log in parsed_logs if log['step'] == 'item_processed')
        self.assertEqual(item_log['outcome'], 'success')
        self.assertEqual(item_log['idempotency_key'], dna)
        self.assertIn('latency_ms', item_log)

        # Verify batch_end
        self.assertEqual(parsed_logs[-1]['step'], 'batch_end')
        self.assertEqual(parsed_logs[-1]['outcome'], 'success')
        self.assertEqual(parsed_logs[-1]['newly_processed'], 1)

if __name__ == '__main__':
    unittest.main()

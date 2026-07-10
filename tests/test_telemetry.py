import unittest
import os
import shutil
import tempfile
import json
import io
import sys
from unittest.mock import patch, MagicMock
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

        # Mock a rule file
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

    def test_structured_logs(self):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        dna = "V100"
        with open(input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            run_batch(correlation_id="test-corr-id")
            output = fake_out.getvalue()

        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
        self.assertTrue(len(log_lines) >= 3) # start, parse, end (and maybe persist)

        logs = [json.loads(line[9:]) for line in log_lines]

        # Verify correlation_id
        for log in logs:
            self.assertEqual(log['correlation_id'], "test-corr-id")
            self.assertIn('timestamp', log)
            self.assertIn('step', log)
            self.assertIn('outcome', log)

        # Verify specific steps
        steps = [log['step'] for log in logs]
        self.assertIn('start', steps)
        self.assertIn('parse', steps)
        self.assertIn('end', steps)

        # Verify idempotency_key in parse step
        parse_log = next(log for log in logs if log['step'] == 'parse')
        self.assertEqual(parse_log['idempotency_key'], dna)

if __name__ == '__main__':
    unittest.main()

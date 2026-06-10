import unittest
import os
import json
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
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
        self.dna = "V123"
        with open(self.input_file, 'w') as f:
            f.write(f"{self.dna}\n")

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

    def test_structured_logging_format(self):
        """Verify that logs follow the structured format."""
        f = io.StringIO()
        correlation_id = "test-corr-id"
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]

        self.assertTrue(len(log_lines) > 0, "No JSON_LOG lines found")

        for line in log_lines:
            json_str = line.replace('JSON_LOG: ', '', 1)
            log_entry = json.loads(json_str)

            self.assertIn('timestamp', log_entry)
            self.assertEqual(log_entry['correlation_id'], correlation_id)
            self.assertEqual(log_entry['chain_name'], 'dna_batch_parser')
            self.assertIn('step', log_entry)
            self.assertIn('outcome', log_entry)

    def test_canonical_naming_in_output(self):
        """Verify that output files use 'dna_sequence' instead of 'dna'."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(data[0]['dna_sequence'], self.dna)
            self.assertNotIn('dna', data[0])

if __name__ == '__main__':
    unittest.main()

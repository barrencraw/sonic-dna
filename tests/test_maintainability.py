import unittest
import os
import json
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, DNAStatus

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

    def test_canonical_naming_in_output(self):
        """Verify that 'dna_sequence' is used in the JSON output."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertEqual(data[0]['dna_sequence'], dna)

    def test_structured_logging_format(self):
        """Verify that logs have the JSON_LOG: prefix and required fields."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]
        self.assertTrue(len(log_lines) > 0)

        # Check one of the logs
        log_data = json.loads(log_lines[0].replace("JSON_LOG: ", ""))
        self.assertEqual(log_data['correlation_id'], "test-cid")
        self.assertEqual(log_data['actor_id'], "test-actor")
        self.assertIn('timestamp', log_data)
        self.assertIn('chain_name', log_data)
        self.assertIn('step', log_data)
        self.assertIn('outcome', log_data)

    def test_enum_usage_in_logs(self):
        """Verify that outcomes use the DNAStatus enum values."""
        dna = "VOL123"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        # Look for the success log
        success_found = False
        for line in output.split('\n'):
            if "JSON_LOG:" in line:
                log_data = json.loads(line.replace("JSON_LOG: ", ""))
                if log_data['outcome'] == DNAStatus.SUCCESS.value:
                    success_found = True
                    break
        self.assertTrue(success_found)

if __name__ == '__main__':
    unittest.main()

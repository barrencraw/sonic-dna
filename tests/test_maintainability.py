import unittest
import os
import json
import csv
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

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "pan", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL100200\n")

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_guard(self):
        """Verify that 'dna_sequence' is used instead of 'dna' in outputs."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        with open(csv_out, 'r') as f:
            reader = csv.DictReader(f)
            self.assertIn('dna_sequence', reader.fieldnames)
            self.assertNotIn('dna', reader.fieldnames)

    def test_dna_status_enum_guard(self):
        """Verify that terminal outcomes use DNAStatus enum values."""
        run_batch()
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
            outcome = ledger["VOL100200"]['terminal_outcome']
            self.assertEqual(outcome, DNAStatus.SUCCESS.value)

    def test_structured_logging_guard(self):
        """Verify that logs follow the structured JSON format."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]
        self.assertTrue(len(log_lines) > 0)

        for line in log_lines:
            json_str = line.replace("JSON_LOG:", "")
            log_data = json.loads(json_str)
            self.assertEqual(log_data["correlation_id"], "test-id")
            self.assertIn("timestamp", log_data)
            self.assertIn("chain_name", log_data)
            self.assertIn("step", log_data)
            self.assertIn("outcome", log_data)

if __name__ == '__main__':
    unittest.main()

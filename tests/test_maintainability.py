import unittest
import os
import json
import csv
import tempfile
import shutil
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

    def test_naming_alignment_dna_sequence(self):
        """Ensure canonical 'dna_sequence' is used in JSON and CSV outputs."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Check JSON
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])
            self.assertEqual(data[0]['dna_sequence'], dna)

        # Check CSV
        with open(csv_out, 'r') as f:
            reader = csv.DictReader(f)
            self.assertIn('dna_sequence', reader.fieldnames)
            self.assertNotIn('dna', reader.fieldnames)
            row = next(reader)
            self.assertEqual(row['dna_sequence'], dna)

    def test_structured_logging_format(self):
        """Ensure logs follow the JSON_LOG: prefix and contain required fields."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertTrue(len(log_lines) >= 1)

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_data = json.loads(json_str)

            self.assertIn("timestamp", log_data)
            self.assertEqual(log_data["correlation_id"], "test-corr-id")
            self.assertEqual(log_data["chain_name"], "dna_batch_processor")
            self.assertIn("step", log_data)
            self.assertIn("outcome", log_data)
            self.assertEqual(log_data["actor_id"], "test-actor")
            self.assertEqual(log_data["idempotency_key"], dna)

    def test_dna_status_enum_usage(self):
        """Ensure DNAStatus enum values are used in outcomes."""
        # Success case
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        success_log = [line for line in output.splitlines() if "process_sequence" in line][0]
        log_data = json.loads(success_log.replace("JSON_LOG: ", ""))
        self.assertEqual(log_data["outcome"], DNAStatus.SUCCESS.value)

        # Error case
        invalid_dna = "INVALID"
        with open(self.input_file, 'w') as f:
            f.write(invalid_dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        error_log = [line for line in output.splitlines() if "process_sequence" in line and "INVALID" in line][0]
        log_data = json.loads(error_log.replace("JSON_LOG: ", ""))
        self.assertEqual(log_data["outcome"], DNAStatus.ERROR.value)

if __name__ == '__main__':
    unittest.main()

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
        """Verify that 'dna_sequence' is used in JSON and CSV output."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])
            self.assertNotIn('dna_string', data[0])

        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        with open(csv_out, 'r') as f:
            header = f.readline().strip().split(',')
            self.assertIn('dna_sequence', header)
            self.assertNotIn('dna', header)

    def test_structured_logging_presence(self):
        """Verify that JSON_LOG: prefix and required fields are present in logs."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG: ")]
        self.assertTrue(len(log_lines) > 0)

        # Parse the first log line
        log_json = json.loads(log_lines[0].replace("JSON_LOG: ", ""))
        required_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id", "idempotency_key"]
        for field in required_fields:
            self.assertIn(field, log_json)

        self.assertEqual(log_json["correlation_id"], "test-id")
        self.assertEqual(log_json["actor_id"], "test-actor")

    def test_dna_status_enum_usage(self):
        """Verify that DNAStatus enum values are used in the ledger."""
        dna = "V100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS.value)

if __name__ == '__main__':
    unittest.main()

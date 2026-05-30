import os
import json
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def test_naming_alignment_dna_sequence(self):
        """Verify that the output JSON uses 'dna_sequence' instead of 'dna'."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Clear ledger to ensure processing
        ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertTrue(len(data) > 0)
        self.assertIn('dna_sequence', data[0], "Key 'dna_sequence' missing from output JSON")
        self.assertNotIn('dna', data[0], "Legacy key 'dna' found in output JSON")

    def test_structured_logging_format(self):
        """Verify that logs follow the JSON_LOG: {json} format and contain mandatory fields."""
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Clear ledger to ensure processing
        ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]

        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_entry = json.loads(json_str)

            required_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id"]
            for field in required_fields:
                self.assertIn(field, log_entry, f"Mandatory log field '{field}' missing")

if __name__ == '__main__':
    unittest.main()

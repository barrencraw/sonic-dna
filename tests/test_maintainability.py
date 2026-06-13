import unittest
import os
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_structured_logging_format(self):
        """Verify that logs follow the JSON_LOG: prefix and contain required fields."""
        f = io.StringIO()
        # We need some DNA to trigger a log
        os.makedirs('data/raw', exist_ok=True)
        with open('data/raw/toSequence.txt', 'w') as tf:
            tf.write("VOL00000000000\n")

        with redirect_stdout(f):
            try:
                run_batch()
            except Exception:
                pass

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG: ")]

        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        for line in log_lines:
            json_str = line[len("JSON_LOG: "):]
            data = json.loads(json_str)

            self.assertIn("timestamp", data)
            self.assertIn("correlation_id", data)
            self.assertIn("chain_name", data)
            self.assertIn("step", data)
            self.assertIn("outcome", data)
            self.assertEqual(data["chain_name"], "dna_batch_chain")

    def test_canonical_naming_dna_sequence(self):
        """Verify that 'dna_sequence' is used in JSON output instead of 'dna'."""
        os.makedirs('data/raw', exist_ok=True)
        with open('data/raw/toSequence.txt', 'w') as tf:
            tf.write("VOL00000000000\n")

        try:
            run_batch()
        except Exception:
            pass

        json_path = 'data/output/toSequence_parsed.json'
        if os.path.exists(json_path):
            with open(json_path, 'r') as jf:
                data = json.load(jf)
                if len(data) > 0:
                    self.assertIn("dna_sequence", data[0])
                    self.assertNotIn("dna", data[0])

    def test_enum_usage_for_outcomes(self):
        """Verify that outcomes use DNAStatus enum values."""
        f = io.StringIO()
        with open('data/raw/toSequence.txt', 'w') as tf:
            tf.write("VOL00000000000\n")

        # Clear ledger to ensure processing
        ledger_path = 'data/ledger.json'
        if os.path.exists(ledger_path):
            os.remove(ledger_path)

        with redirect_stdout(f):
            try:
                run_batch()
            except Exception:
                pass

        output = f.getvalue()
        parse_logs = [line for line in output.split('\n') if "JSON_LOG:" in line and '"step": "parse"' in line]

        for line in parse_logs:
            json_str = line[line.find("{"):]
            data = json.loads(json_str)
            # outcome can be 'success' or 'error: ...'
            outcome = data["outcome"]
            valid_statuses = [s.value for s in DNAStatus]
            is_valid = any(outcome.startswith(s) for s in valid_statuses)
            self.assertTrue(is_valid, f"Invalid outcome: {outcome}")

if __name__ == '__main__':
    unittest.main()

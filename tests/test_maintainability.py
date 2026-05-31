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
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup basic structure
        os.makedirs("data/raw")
        os.makedirs("rules")

        # Mock a rule
        with open("rules/volume.json", "w") as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "v": {"description": "v", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_naming_alignment_dna_sequence(self):
        """Assert that 'dna_sequence' is used instead of 'dna' in outputs."""
        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL5\n")

        run_batch()

        json_path = "data/output/toSequence_parsed.json"
        with open(json_path, "r") as f:
            data = json.load(f)
            self.assertIn("dna_sequence", data[0])
            self.assertNotIn("dna", data[0])

    def test_structured_logging_format(self):
        """Assert that logs follow the JSON_LOG: format with required fields."""
        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL5\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cid")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertTrue(len(log_lines) > 0, "No JSON_LOG lines found")

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_data = json.loads(json_str)
            self.assertIn("correlation_id", log_data)
            self.assertIn("chain_name", log_data)
            self.assertIn("step", log_data)
            self.assertIn("outcome", log_data)
            self.assertEqual(log_data["correlation_id"], "test-cid")

    def test_enum_usage_in_ledger(self):
        """Assert that ledger uses explicit terminal states from DNAStatus enum."""
        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL5\n")

        run_batch()

        ledger_path = "data/processed_ledger.json"
        with open(ledger_path, "r") as f:
            ledger = json.load(f)
            self.assertEqual(ledger["VOL5"]["terminal_outcome"], DNAStatus.SUCCESS.value)

if __name__ == "__main__":
    unittest.main()

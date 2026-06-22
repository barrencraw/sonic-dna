
import unittest
import os
import json
import csv
import shutil
import tempfile
from utils.dna_ui import main as run_batch, DNAStatus
from utils.dna_calculator import DNACalculator

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.project_root = os.getcwd()
        os.chdir(self.test_dir)

        # Setup data directory
        os.makedirs("data/raw", exist_ok=True)
        os.makedirs("data/output", exist_ok=True)
        os.makedirs("rules", exist_ok=True)

        # Copy rules from project root
        rules_src = os.path.join(self.project_root, "rules")
        for item in os.listdir(rules_src):
            s = os.path.join(rules_src, item)
            d = os.path.join("rules", item)
            if os.path.isfile(s):
                shutil.copy2(s, d)

    def tearDown(self):
        os.chdir(self.project_root)
        shutil.rmtree(self.test_dir)

    def test_canonical_naming_in_outputs(self):
        """Verify that 'dna_sequence' is used in JSON and CSV outputs."""
        dna_seq = "VOL00000000001"
        with open("data/raw/toSequence.txt", "w") as f:
            f.write(f"{dna_seq}\n")

        run_batch(correlation_id="test-cor-id", actor_id="test-actor")

        # Check JSON output
        json_path = "data/output/toSequence_parsed.json"
        with open(json_path, "r") as f:
            data = json.load(f)
            self.assertTrue(len(data) > 0)
            self.assertIn("dna_sequence", data[0])
            self.assertNotIn("dna", data[0])
            self.assertEqual(data[0]["dna_sequence"], dna_seq)

        # Check CSV output
        csv_path = "data/output/toSequence_parsed.csv"
        with open(csv_path, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            self.assertTrue(len(rows) > 0)
            self.assertIn("dna_sequence", reader.fieldnames)
            self.assertNotIn("dna", reader.fieldnames)
            self.assertEqual(rows[0]["dna_sequence"], dna_seq)

    def test_dna_status_enum_usage(self):
        """Verify DNAStatus enum members have expected values."""
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.ERROR.value, "error")
        self.assertEqual(DNAStatus.SKIPPED.value, "skipped")
        self.assertEqual(DNAStatus.PROCESSING.value, "processing")

    def test_structured_log_format(self):
        """Verify structured logs contain required keys via captured stdout."""
        import io
        from contextlib import redirect_stdout

        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL00000000002\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-cor-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG: ")]
        self.assertTrue(len(log_lines) > 0)

        for line in log_lines:
            json_str = line[len("JSON_LOG: "):]
            entry = json.loads(json_str)
            required_keys = ["timestamp", "correlation_id", "chain_name", "step", "outcome"]
            for key in required_keys:
                self.assertIn(key, entry)
            self.assertEqual(entry["correlation_id"], "test-cor-id")
            self.assertEqual(entry["actor_id"], "test-actor")

if __name__ == "__main__":
    unittest.main()

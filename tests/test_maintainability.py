import unittest
import os
import io
import json
import shutil
import tempfile
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_structured_logging(self):
        """Verify that the batch parser produces correctly formatted JSON logs."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-123", base_dir=self.test_dir)

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertGreater(len(log_lines), 0)

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_entry = json.loads(json_str)

            self.assertIn("timestamp", log_entry)
            self.assertEqual(log_entry["correlation_id"], "test-123")
            self.assertEqual(log_entry["chain_name"], "dna_batch_parsing")
            self.assertIn("step", log_entry)
            self.assertIn("outcome", log_entry)

    def test_dedupe_logging(self):
        """Verify logging for deduplication hits."""
        # Process once
        run_batch(correlation_id="first", base_dir=self.test_dir)

        # Prepare for second run
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="second", base_dir=self.test_dir)

        output = f.getvalue()
        self.assertIn('"step": "dedupe"', output)
        self.assertIn('"outcome": "skip"', output)

if __name__ == '__main__':
    unittest.main()

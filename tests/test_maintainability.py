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
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
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

    def test_structured_logging_presence(self):
        """Verify that logs have JSON_LOG: prefix and contain required fields."""
        f = io.StringIO()
        correlation_id = "test-correlation-id"
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id)

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]

        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        found_correlation_id = False
        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_entry = json.loads(json_str)
            self.assertIn("timestamp", log_entry)
            self.assertIn("correlation_id", log_entry)
            self.assertIn("chain_name", log_entry)
            self.assertIn("step", log_entry)
            self.assertIn("outcome", log_entry)
            if log_entry["correlation_id"] == correlation_id:
                found_correlation_id = True

        self.assertTrue(found_correlation_id, f"Correlation ID {correlation_id} not found in logs")

    def test_canonical_naming_dna_sequence(self):
        """Verify that dna_sequence is used in the output JSON instead of dna."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        self.assertTrue(len(data) > 0)
        entry = data[0]
        self.assertIn('dna_sequence', entry)
        self.assertNotIn('dna', entry)

if __name__ == '__main__':
    unittest.main()

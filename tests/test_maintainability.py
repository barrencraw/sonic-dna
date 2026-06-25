import unittest
import io
import json
import os
import shutil
import tempfile
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
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

    def test_structured_logging_format(self):
        """Verify that batch processing emits correctly formatted JSON logs."""
        f = io.StringIO()
        correlation_id = "test-correlation-id"
        actor_id = "test-actor"

        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG: ")]

        self.assertGreater(len(log_lines), 0, "No structured logs found")

        for line in log_lines:
            json_str = line.replace("JSON_LOG: ", "")
            log_entry = json.loads(json_str)

            # Verify mandatory fields
            mandatory_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome", "actor_id"]
            for field in mandatory_fields:
                self.assertIn(field, log_entry, f"Missing field '{field}' in log entry: {log_entry}")

            self.assertEqual(log_entry["correlation_id"], correlation_id)
            self.assertEqual(log_entry["actor_id"], actor_id)
            self.assertEqual(log_entry["chain_name"], "dna_batch")

        # Verify specific steps exist
        steps = [entry["step"] for entry in [json.loads(l.replace("JSON_LOG: ", "")) for l in log_lines]]
        self.assertIn("batch_start", steps)
        self.assertIn("item_processed", steps)
        self.assertIn("batch_end", steps)

    def test_structured_logging_error_path(self):
        """Verify that batch processing emits correctly formatted JSON logs on error."""
        f = io.StringIO()
        correlation_id = "test-error-correlation-id"

        # Point to non-existent rules folder
        os.chdir(self.test_dir)
        # We'll mock the rules folder to be missing
        shutil.rmtree(self.rules_dir)

        with redirect_stdout(f):
            try:
                run_batch(correlation_id=correlation_id)
            except Exception:
                pass

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith("JSON_LOG: ")]

        # The last log should be batch_end with error outcome
        last_log = json.loads(log_lines[-1].replace("JSON_LOG: ", ""))
        self.assertEqual(last_log["step"], "batch_end")
        self.assertEqual(last_log["outcome"], "error")
        self.assertIn("error_detail", last_log)

if __name__ == '__main__':
    unittest.main()

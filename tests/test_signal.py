import unittest
import json
import io
import os
import shutil
import tempfile
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, SUCCESS, DEDUPE

class TestObservabilitySignal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup basic structure
        os.makedirs("data/raw")
        os.makedirs("rules")

        # Create a dummy rule
        rule_content = {
            "variable": "TestVar",
            "prefix": "T",
            "subvars": {
                "val": {"description": "test", "min": 0, "max": 9, "pad": 1}
            }
        }
        with open("rules/rule_test.json", "w") as f:
            json.dump(rule_content, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs_format(self):
        input_path = "data/raw/toSequence.txt"
        with open(input_path, "w") as f:
            f.write("T5\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        self.assertTrue(len(logs) >= 2, "Should have at least start and complete logs")

        # Verify first log
        first_log = json.loads(logs[0].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(first_log["correlation_id"], "test-corr")
        self.assertEqual(first_log["actor_id"], "test-actor")
        self.assertEqual(first_log["step"], "batch_start")

        # Verify string_processed log
        processed_log = json.loads(logs[1].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(processed_log["step"], "string_processed")
        self.assertEqual(processed_log["outcome"], SUCCESS)
        self.assertEqual(processed_log["idempotency_key"], "T5")
        self.assertIn("latency_ms", processed_log)

    def test_idempotency_signal(self):
        input_path = "data/raw/toSequence.txt"
        with open(input_path, "w") as f:
            f.write("T5\n")

        # Run once
        run_batch(correlation_id="test-corr-1", actor_id="test-actor")

        # Run again with same DNA
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-2", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        # Find dedupe_hit log
        dedupe_logs = [json.loads(line.replace("[OBSERVABILITY] ", "")) for line in logs if "dedupe_hit" in line]
        self.assertEqual(len(dedupe_logs), 1)
        self.assertEqual(dedupe_logs[0]["outcome"], DEDUPE)
        self.assertEqual(dedupe_logs[0]["idempotency_key"], "T5")

if __name__ == "__main__":
    unittest.main()

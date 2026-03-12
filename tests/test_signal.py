import os
import unittest
import io
import sys
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create necessary folders
        os.makedirs("data/raw")
        os.makedirs("data/output")
        os.makedirs("rules")

        # Create a dummy rule
        dummy_rule = {
            "variable": "TestVar",
            "prefix": "TST",
            "subvars": {
                "val": {"description": "test", "min": 0, "max": 9, "pad": 1}
            }
        }
        with open("rules/rules_Test.json", "w") as f:
            json.dump(dummy_rule, f)

        self.input_file = "data/raw/toSequence.txt"

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs(self):
        # Prepare input
        with open(self.input_file, "w") as f:
            f.write("TST1\n")

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            run_batch(correlation_id="test-id", actor_id="test-actor")
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        lines = [line for line in output.split("\n") if "[OBSERVABILITY]" in line]

        # Check start log
        start_logs = [l for l in lines if "step=start" in l]
        self.assertTrue(len(start_logs) >= 1)
        self.assertIn("correlation_id=test-id", start_logs[0])
        self.assertIn("actor_id=test-actor", start_logs[0])
        self.assertIn("outcome=SUCCESS", start_logs[0])

        # Check process_dna log
        process_logs = [l for l in lines if "step=process_dna" in l]
        self.assertTrue(len(process_logs) >= 1)
        self.assertIn("idempotency_key=TST1", process_logs[0])
        self.assertIn("outcome=SUCCESS", process_logs[0])
        self.assertIn("latency_ms=", process_logs[0])

        # Check terminal log
        terminal_logs = [l for l in lines if "step=terminal" in l]
        self.assertTrue(len(terminal_logs) >= 1)
        self.assertIn("outcome=SUCCESS", terminal_logs[0])
        self.assertIn("latency_ms=", terminal_logs[0])

if __name__ == "__main__":
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestDNABatchRegression(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for the test
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup data and rules directories
        os.makedirs("data/raw")
        os.makedirs("data/output")
        # Fallback for CI/isolated environments: create a dummy rule
        os.makedirs("rules")
        with open("rules/rules_Volume.json", "w") as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {
                        "min": 0, "max": 1000, "pad": 4,
                        "description": "amp"
                    },
                    "lr": {
                        "min": 0, "max": 100, "pad": 3,
                        "description": "lr"
                    },
                    "sur": {
                        "min": 0, "max": 10, "pad": 2,
                        "description": "sur"
                    },
                    "head": {
                        "min": 0, "max": 60, "pad": 2,
                        "description": "head"
                    }
                }
            }, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_observability_logs_and_terminal_states(self):
        # Prepare input
        # VOL08900750712 is a valid string based on the rule above
        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL08900750712\n")
            f.write("INVALID\n")
            f.write("VOL08900750712\n")  # Dedupe

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()
        logs = []
        for line in output.splitlines():
            if line.startswith('{"prefix": "[OBSERVABILITY]"'):
                logs.append(json.loads(line))

        # Check logs
        self.assertTrue(any(log["step"] == "start" for log in logs))

        # SUCCESS check
        success_log = next(log for log in logs if log.get("idempotency_key") == "VOL08900750712" and log.get("outcome") == "SUCCESS")
        self.assertEqual(success_log["outcome"], "SUCCESS")
        self.assertEqual(success_log["correlation_id"], "test-corr")
        self.assertEqual(success_log["actor_id"], "test-actor")

        # ERROR check
        error_log = next(log for log in logs if log.get("idempotency_key") == "INVALID")
        self.assertEqual(error_log["outcome"], "ERROR")

        # DEDUPE check
        dedupe_logs = [log for log in logs if log.get("outcome") == "DEDUPE"]
        self.assertEqual(len(dedupe_logs), 1)
        self.assertEqual(dedupe_logs[0]["idempotency_key"], "VOL08900750712")

        # Final complete log
        complete_log = next(log for log in logs if log["step"] == "complete")
        self.assertEqual(complete_log["outcome"], "SUCCESS")
        self.assertEqual(complete_log["new_processed_count"], 2) # VOL08900750712, INVALID

    def test_atomic_persistence(self):
        with open("data/raw/toSequence.txt", "w") as f:
            f.write("VOL08900750712\n")

        run_batch(correlation_id="test-corr", actor_id="test-actor")

        # Verify all 3 files exist
        self.assertTrue(os.path.exists("data/output/toSequence_parsed.json"))
        self.assertTrue(os.path.exists("data/output/toSequence_parsed.csv"))
        self.assertTrue(os.path.exists("data/processed_ledger.json"))

        # Verify ledger content
        with open("data/processed_ledger.json", "r") as f:
            ledger = json.load(f)
            self.assertIn("VOL08900750712", ledger)
            self.assertEqual(ledger["VOL08900750712"]["terminal_outcome"], "SUCCESS")

if __name__ == "__main__":
    unittest.main()

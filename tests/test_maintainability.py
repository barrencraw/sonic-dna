import unittest
import json
import os
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import Outcome, ProcessingResult, main as run_batch

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintainability')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_processing_result_dataclass(self):
        """Verify ProcessingResult structure."""
        res = ProcessingResult(
            dna="VOL08900750712",
            outcome=Outcome.SUCCESS,
            rule="Volume",
            values={"val": 123}
        )
        self.assertEqual(res.dna, "VOL08900750712")
        self.assertEqual(res.outcome, Outcome.SUCCESS)
        self.assertEqual(res.rule, "Volume")
        self.assertEqual(res.values["val"], 123)

    def test_structured_logging_presence(self):
        """Verify that observability logs contain the required fields."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()

        # Check for [OBSERVABILITY] entries
        obs_lines = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]
        self.assertTrue(len(obs_lines) > 0, "Should have observability logs")

        # Parse the last one (batch_end)
        last_log = json.loads(obs_lines[-1].replace("[OBSERVABILITY] ", ""))

        required_fields = [
            "correlation_id", "chain_name", "step", "outcome",
            "latency_ms", "actor_id", "idempotency_key", "timestamp"
        ]
        for field in required_fields:
            self.assertIn(field, last_log, f"Missing required field: {field}")

        self.assertEqual(last_log["correlation_id"], "test-corr-id")
        self.assertEqual(last_log["actor_id"], "test-actor")
        self.assertEqual(last_log["chain_name"], "dna_batch_chain")

    def test_error_classification_in_logs(self):
        """Verify that errors are correctly classified in logs."""
        invalid_dna = "INVALID123"
        with open(self.input_file, 'w') as f:
            f.write(invalid_dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="error-test-id", actor_id="error-actor")

        output = f.getvalue()
        obs_lines = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        # Find the parse_dna step for the invalid DNA
        parse_logs = [json.loads(line.replace("[OBSERVABILITY] ", ""))
                      for line in obs_lines if '"step": "parse_dna"' in line]

        self.assertTrue(len(parse_logs) > 0)
        error_log = parse_logs[0]
        self.assertEqual(error_log["outcome"], Outcome.ERROR.value)
        self.assertIn("error", error_log)
        self.assertTrue(len(error_log["error"]) > 0)

if __name__ == '__main__':
    unittest.main()

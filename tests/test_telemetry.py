import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_telemetry')
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

    def test_batch_processing_telemetry(self):
        """Verify that run_batch emits structured logs for each sequence and for the commit."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="telemetry-test", actor_id="telemetry-actor")

        output = f.getvalue().strip()
        logs = [line for line in output.split('\n') if line.startswith("JSON_LOG:")]

        self.assertTrue(len(logs) >= 2, f"Should have at least 2 logs (process + commit), got {len(logs)}")

        # Check process log
        process_log = json.loads(logs[0][9:])
        self.assertEqual(process_log["step"], "process_sequence")
        self.assertEqual(process_log["idempotency_key"], dna)
        self.assertEqual(process_log["correlation_id"], "telemetry-test")
        self.assertEqual(process_log["outcome"], "success")

        # Check commit log
        commit_log = json.loads(logs[-1][9:])
        self.assertEqual(commit_log["step"], "commit")
        self.assertEqual(commit_log["outcome"], "success")
        self.assertEqual(commit_log["idempotency_key"], "batch")

if __name__ == '__main__':
    unittest.main()

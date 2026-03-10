import os
import json
import shutil
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_observability_logs_and_terminal_states(self):
        dna_success = "VOL08900750712"
        dna_error = "INVALID_DNA"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_success}\n{dna_error}\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-correlation-id", actor_id="test-actor")

        output = f.getvalue()
        lines = output.splitlines()

        # Verify [OBSERVABILITY] logs
        obs_logs = [line for line in lines if line.startswith("[OBSERVABILITY]")]
        self.assertTrue(len(obs_logs) >= 3, "Should have at least start, process, and complete logs")

        found_start = False
        found_success = False
        found_error = False
        found_complete = False

        for log in obs_logs:
            data = json.loads(log.replace("[OBSERVABILITY] ", ""))
            self.assertEqual(data["correlation_id"], "test-correlation-id")
            self.assertEqual(data["chain_name"], "dna_batch_processing")
            self.assertIn("timestamp", data)
            self.assertEqual(data["actor_id"], "test-actor")

            if data["step"] == "start":
                found_start = True
            elif data["step"] == "process_dna":
                if data["outcome"] == "SUCCESS":
                    found_success = True
                    self.assertEqual(data["idempotency_key"], dna_success)
                    self.assertIn("latency_ms", data)
                elif data["outcome"] == "ERROR":
                    found_error = True
                    self.assertEqual(data["idempotency_key"], dna_error)
                    self.assertIn("latency_ms", data)
            elif data["step"] == "complete":
                found_complete = True
                self.assertEqual(data["outcome"], "SUCCESS")
                self.assertIn("latency_ms", data)

        self.assertTrue(found_start, "Missing start log")
        self.assertTrue(found_success, "Missing SUCCESS process log")
        self.assertTrue(found_error, "Missing ERROR process log")
        self.assertTrue(found_complete, "Missing complete log")

        # Verify ledger terminal states
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_success]['terminal_outcome'], "SUCCESS")
        self.assertEqual(ledger[dna_error]['terminal_outcome'], "ERROR")

    def test_idempotency_dedupe_signal(self):
        dna = "VOL08900750712"

        # First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch(correlation_id="id-1")

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="id-2")

        output = f.getvalue()
        obs_logs = [line for line in output.splitlines() if line.startswith("[OBSERVABILITY]")]

        found_dedupe = False
        for log in obs_logs:
            data = json.loads(log.replace("[OBSERVABILITY] ", ""))
            if data["step"] == "process_dna" and data["outcome"] == "DEDUPE":
                found_dedupe = True
                self.assertEqual(data["idempotency_key"], dna)

        self.assertTrue(found_dedupe, "Missing DEDUPE signal in observability logs")

if __name__ == '__main__':
    unittest.main()

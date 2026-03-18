import unittest
import json
import io
import contextlib
import os
import shutil
import uuid
from utils.dna_ui import main as run_batch

class TestObservability(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_obs')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_log_fields_presence(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())
        actor_id = "test_actor"

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        lines = [line for line in output.split("\n") if line.startswith("[OBSERVABILITY]")]

        self.assertTrue(len(lines) >= 3, "Should have at least start, process_dna, and complete logs")

        for line in lines:
            json_str = line.replace("[OBSERVABILITY] ", "")
            log_entry = json.loads(json_str)

            self.assertIn("timestamp", log_entry)
            self.assertIn("correlation_id", log_entry)
            self.assertIn("actor_id", log_entry)
            self.assertIn("chain_name", log_entry)
            self.assertIn("step", log_entry)
            self.assertIn("outcome", log_entry)
            self.assertIn("latency_ms", log_entry)
            self.assertIn("idempotency_key", log_entry)

            self.assertEqual(log_entry["correlation_id"], correlation_id)
            self.assertEqual(log_entry["actor_id"], actor_id)
            self.assertEqual(log_entry["chain_name"], "dna_batch_chain")

            # Outcome should be uppercase
            self.assertTrue(log_entry["outcome"].isupper(), f"Outcome {log_entry['outcome']} should be uppercase")

        # Check specific steps
        steps = [json.loads(line.replace("[OBSERVABILITY] ", ""))["step"] for line in lines]
        self.assertIn("start_batch", steps)
        self.assertIn("process_dna", steps)
        self.assertIn("complete_batch", steps)

    def test_dedupe_log(self):
        dna = "VOL08900750712"
        # First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        # Second run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        lines = [line for line in output.split("\n") if line.startswith("[OBSERVABILITY]")]

        process_dna_logs = [json.loads(line.replace("[OBSERVABILITY] ", ""))
                            for line in lines if json.loads(line.replace("[OBSERVABILITY] ", ""))["step"] == "process_dna"]

        self.assertEqual(len(process_dna_logs), 1)
        self.assertEqual(process_dna_logs[0]["outcome"], "DEDUPE")
        self.assertEqual(process_dna_logs[0]["idempotency_key"], dna)

if __name__ == '__main__':
    unittest.main()

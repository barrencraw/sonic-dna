import os
import json
import shutil
import unittest
import uuid
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, Outcome

class TestDNABatchHardened(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_hardened')
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

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())
        actor_id = "test_runner"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(logs) >= 2, "Should have at least START and END logs")

        # Check START log
        start_log = json.loads(logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['correlation_id'], correlation_id)
        self.assertEqual(start_log['actor_id'], actor_id)
        self.assertEqual(start_log['step'], 'start_batch')
        self.assertEqual(start_log['outcome'], Outcome.START.value)
        self.assertIn('timestamp', start_log)

        # Check process_dna log
        process_log = [l for l in logs if 'process_dna' in l][0]
        process_log_data = json.loads(process_log.replace('[OBSERVABILITY] ', ''))
        self.assertEqual(process_log_data['correlation_id'], correlation_id)
        self.assertEqual(process_log_data['outcome'], Outcome.SUCCESS.value)
        self.assertEqual(process_log_data['idempotency_key'], dna)
        self.assertIn('latency_ms', process_log_data)

    def test_idempotency_with_new_outcome(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())
        run_batch(correlation_id=correlation_id, actor_id="test_runner")

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna]['terminal_outcome'], Outcome.SUCCESS.value)

        # Second run should skip
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id="test_runner")

        output = f.getvalue()
        self.assertIn(f"outcome\": \"{Outcome.SKIPPED.value}\"", output)

if __name__ == '__main__':
    unittest.main()

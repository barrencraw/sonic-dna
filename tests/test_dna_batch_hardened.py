import os
import json
import shutil
import unittest
import uuid
import io
import sys
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestDNABatchHardened(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_hardened')
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

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = str(uuid.uuid4())
        actor_id = "test_actor"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(logs) >= 3, f"Should have at least 3 observability logs (start, process, end). Found: {len(logs)}")

        # Verify first log (batch_start)
        start_log = json.loads(logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['correlation_id'], correlation_id)
        self.assertEqual(start_log['actor_id'], actor_id)
        self.assertEqual(start_log['step'], 'batch_start')

        # Verify process log
        process_log = json.loads(logs[1].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(process_log['correlation_id'], correlation_id)
        self.assertEqual(process_log['idempotency_key'], dna)
        self.assertEqual(process_log['outcome'], 'SUCCESS')
        self.assertIn('latency_ms', process_log)

    def test_atomicity_simulation(self):
        # We want to ensure that if we have a failure during the batch,
        # the ledger and outputs stay in sync.
        # Since we implemented atomic swap at the end of the batch,
        # let's verify that a successful batch updates all three files.

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

        with open(self.json_output, 'r') as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['dna'], dna)

    def test_idempotency_behavior(self):
        # Verify that dedupe works and emits correct observability logs
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # First time

        # Second time
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        # Look for DEDUPE log
        dedupe_logs = [json.loads(line.replace('[OBSERVABILITY] ', '')) for line in logs if 'DEDUPE' in line]
        self.assertEqual(len(dedupe_logs), 1)
        self.assertEqual(dedupe_logs[0]['idempotency_key'], dna)
        self.assertEqual(dedupe_logs[0]['outcome'], 'DEDUPE')

if __name__ == '__main__':
    unittest.main()

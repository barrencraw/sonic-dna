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

    def test_observability_logs_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        correlation_id = "test-corr-id"
        actor_id = "test-actor"

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id=correlation_id, actor_id=actor_id)

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(obs_logs) >= 3, f"Expected at least 3 observability logs, got {len(obs_logs)}")

        # Verify first log is 'start'
        start_log = json.loads(obs_logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['step'], 'start')
        self.assertEqual(start_log['correlation_id'], correlation_id)
        self.assertEqual(start_log['actor_id'], actor_id)
        self.assertIn('timestamp', start_log)

        # Verify DNA processing log
        proc_log = None
        for log_line in obs_logs:
            parsed = json.loads(log_line.replace('[OBSERVABILITY] ', ''))
            if parsed['step'] == 'process_dna':
                proc_log = parsed
                break

        self.assertIsNotNone(proc_log)
        self.assertEqual(proc_log['outcome'], 'SUCCESS')
        self.assertEqual(proc_log['idempotency_key'], dna)
        self.assertIn('latency_ms', proc_log)

        # Verify completion log
        comp_log = json.loads(obs_logs[-1].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(comp_log['step'], 'complete')
        self.assertEqual(comp_log['outcome'], 'SUCCESS')

if __name__ == '__main__':
    unittest.main()

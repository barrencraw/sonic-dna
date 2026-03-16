import os
import json
import shutil
import unittest
import io
import sys
from utils.dna_ui import main as run_batch

class TestSignal(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_signal')
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

        # Capture stdout
        captured_output = io.StringIO()
        sys.stdout = captured_output

        try:
            run_batch(correlation_id="test-cor-id", actor_id="test-actor")
        finally:
            sys.stdout = sys.__stdout__

        output = captured_output.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(obs_logs) >= 3, f"Expected at least 3 observability logs, got {len(obs_logs)}")

        # Check 'start' log
        start_log = json.loads(obs_logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['step'], 'start')
        self.assertEqual(start_log['correlation_id'], 'test-cor-id')
        self.assertEqual(start_log['actor_id'], 'test-actor')

        # Check 'process_dna' log
        process_log = json.loads(obs_logs[1].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(process_log['step'], 'process_dna')
        self.assertEqual(process_log['outcome'], 'SUCCESS')
        self.assertEqual(process_log['idempotency_key'], dna)
        self.assertIn('latency_ms', process_log)

        # Check 'complete' log
        complete_log = json.loads(obs_logs[-1].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(complete_log['step'], 'complete')
        self.assertIn('latency_ms', complete_log)

if __name__ == '__main__':
    unittest.main()

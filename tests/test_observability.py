import os
import json
import shutil
import unittest
import io
import contextlib
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

    def test_observability_logs(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertGreaterEqual(len(obs_logs), 3) # start, process, complete

        found_start = False
        found_process = False
        found_complete = False

        for log_line in obs_logs:
            json_str = log_line.replace('[OBSERVABILITY] ', '')
            data = json.loads(json_str)
            self.assertEqual(data['correlation_id'], "test-corr-id")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertIn('latency_ms', data)
            self.assertIn('timestamp', data)

            if data['step'] == 'start_batch':
                found_start = True
            elif data['step'] == 'process_dna':
                found_process = True
                self.assertEqual(data['idempotency_key'], dna)
                self.assertEqual(data['outcome'], "SUCCESS")
            elif data['step'] == 'complete_batch':
                found_complete = True

        self.assertTrue(found_start)
        self.assertTrue(found_process)
        self.assertTrue(found_complete)

if __name__ == '__main__':
    unittest.main()

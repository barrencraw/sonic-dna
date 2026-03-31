import unittest
import json
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, Outcome, ProcessingResult
import os
import shutil

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')

        # Backup and clear data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintainability')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_log_structure(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(obs_logs) >= 3, "Should have at least start, processing, and end logs")

        for log in obs_logs:
            json_str = log.replace('[OBSERVABILITY] ', '')
            data = json.loads(json_str)
            self.assertEqual(data['correlation_id'], "test-corr")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertEqual(data['chain_name'], "dna_batch_chain")
            self.assertIn('step', data)
            self.assertIn('outcome', data)
            self.assertIn('latency_ms', data)
            self.assertIn('timestamp', data)

    def test_error_classification(self):
        # Invalid DNA string
        dna = "INVALID_DNA"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        # Find the processing log for the invalid DNA
        proc_log = None
        for log in obs_logs:
            data = json.loads(log.replace('[OBSERVABILITY] ', ''))
            if data['step'] == 'processing':
                proc_log = data
                break

        self.assertIsNotNone(proc_log)
        self.assertEqual(proc_log['outcome'], 'error')
        self.assertEqual(proc_log['idempotency_key'], dna)

if __name__ == '__main__':
    unittest.main()

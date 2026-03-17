import unittest
import os
import json
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch

class TestObservability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        if os.path.exists(self.data_folder):
            self.backup_folder = os.path.join(self.project_root, 'data_backup_obs')
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        backup = os.path.join(self.project_root, 'data_backup_obs')
        if os.path.exists(backup):
            shutil.move(backup, self.data_folder)

    def test_observability_logs_and_naming(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]

        self.assertTrue(len(logs) >= 3, "Should have at least start, process_dna, and batch_complete logs")

        found_process = False
        for log_line in logs:
            data = json.loads(log_line.replace('[OBSERVABILITY] ', ''))
            self.assertEqual(data['correlation_id'], "test-corr-id")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertEqual(data['chain_name'], "dna_batch_chain")
            self.assertIn('timestamp', data)
            self.assertIn('step', data)
            self.assertIn('outcome', data)

            # Outcome should be uppercase
            self.assertEqual(data['outcome'], data['outcome'].upper())

            if data['step'] == 'process_dna':
                found_process = True
                self.assertEqual(data['idempotency_key'], dna)
                self.assertEqual(data['outcome'], 'SUCCESS')
                self.assertIn('latency_ms', data)

        self.assertTrue(found_process, "Should have found a process_dna step")

        # Check ledger for uppercase outcome
        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'SUCCESS')

if __name__ == '__main__':
    unittest.main()

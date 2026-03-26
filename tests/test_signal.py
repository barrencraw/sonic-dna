import os
import json
import shutil
import unittest
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, Outcome

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

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_observability_logs_and_ledger_outcomes(self):
        # DNA for Volume (prefix 'VOL')
        dna_success = "VOL08900750712"
        dna_error = "INVALID_DNA"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_success}\n{dna_error}\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()

        # Verify observability logs
        obs_logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertGreater(len(obs_logs), 0)

        found_success = False
        found_error = False

        for log in obs_logs:
            data = json.loads(log.replace('[OBSERVABILITY] ', ''))
            self.assertEqual(data['correlation_id'], "test-corr-id")
            self.assertEqual(data['actor_id'], "test-actor")
            self.assertIn('chain_name', data)
            self.assertIn('step', data)
            self.assertIn('outcome', data)
            self.assertIn('timestamp', data)

            if data['outcome'] == Outcome.SUCCESS.value and data.get('idempotency_key') == dna_success:
                found_success = True
                self.assertIn('latency_ms', data)
            if data['outcome'] == Outcome.ERROR.value and data.get('idempotency_key') == dna_error:
                found_error = True
                self.assertIn('error', data)

        self.assertTrue(found_success, "Success log not found for dna_success")
        self.assertTrue(found_error, "Error log not found for dna_error")

        # Verify ledger outcomes are uppercase
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_success]['terminal_outcome'], Outcome.SUCCESS.value)
        self.assertEqual(ledger[dna_error]['terminal_outcome'], Outcome.ERROR.value)

        # Verify all ledger outcomes are valid Outcome values
        valid_outcomes = [o.value for o in Outcome]
        for key in ledger:
            self.assertIn(ledger[key]['terminal_outcome'], valid_outcomes)

if __name__ == '__main__':
    unittest.main()

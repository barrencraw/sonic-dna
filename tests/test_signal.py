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

    def test_observability_logs_and_ledger_naming(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-id", actor_id="test-actor")

        output = f.getvalue()

        # Verify observability logs
        log_lines = [line for line in output.split('\n') if line.startswith("[OBSERVABILITY]")]
        self.assertTrue(len(log_lines) >= 2)

        # Parse first log line (batch_start)
        start_log = json.loads(log_lines[0].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(start_log['correlation_id'], "test-id")
        self.assertEqual(start_log['actor_id'], "test-actor")
        self.assertEqual(start_log['step'], "batch_start")
        self.assertEqual(start_log['outcome'], "START")

        # Parse parse log line
        parse_log = json.loads(log_lines[1].replace("[OBSERVABILITY] ", ""))
        self.assertEqual(parse_log['step'], "dna_parse")
        self.assertEqual(parse_log['outcome'], "SUCCESS")
        self.assertEqual(parse_log['idempotency_key'], dna)
        self.assertIn('latency_ms', parse_log)
        self.assertIn('timestamp', parse_log)

        # Verify ledger outcome naming (should be uppercase SUCCESS)
        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'SUCCESS')

    def test_error_classification_in_ledger(self):
        dna = "INVALID-DNA"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-err-id", actor_id="test-actor")

        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)

        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'ERROR')
        self.assertTrue(ledger[dna]['error'].startswith('ERROR:'))

if __name__ == '__main__':
    unittest.main()

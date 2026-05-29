import os
import json
import shutil
import unittest
import io
import contextlib
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintainability')
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

    def test_structured_logging(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        log_lines = [line for line in output.splitlines() if line.startswith("JSON_LOG:")]

        self.assertTrue(len(log_lines) >= 3) # start, process_sequence, end

        # Check start log
        start_log = json.loads(log_lines[0].replace("JSON_LOG: ", ""))
        self.assertEqual(start_log['step'], 'start')
        self.assertIn('correlation_id', start_log)
        self.assertEqual(start_log['chain_name'], 'dna_batch_parsing')

        # Check process log
        process_log = json.loads(log_lines[1].replace("JSON_LOG: ", ""))
        self.assertEqual(process_log['step'], 'process_sequence')
        self.assertEqual(process_log['dna'], dna)
        self.assertEqual(process_log['outcome'], TerminalOutcome.SUCCESS.value)

    def test_ledger_uppercase_outcomes(self):
        dna_success = "VOL08900750712"
        dna_error = "INVALID_DNA"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_success}\n{dna_error}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_success]['terminal_outcome'], "SUCCESS")
        self.assertEqual(ledger[dna_error]['terminal_outcome'], "PARSE_ERROR")

if __name__ == '__main__':
    unittest.main()

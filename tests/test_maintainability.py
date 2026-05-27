import os
import json
import csv
import unittest
import shutil
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
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

    def test_canonical_naming_and_enums(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id")

        log_output = f.getvalue()

        # Check JSON output for dna_sequence
        with open(self.json_output, 'r') as jf:
            data = json.load(jf)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

        # Check CSV output for dna_sequence
        with open(self.csv_output, 'r') as cf:
            reader = csv.DictReader(cf)
            self.assertIn('dna_sequence', reader.fieldnames)
            self.assertNotIn('dna', reader.fieldnames)

        # Check ledger for uppercase TerminalOutcome
        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)
            self.assertEqual(ledger[dna]['terminal_outcome'], TerminalOutcome.SUCCESS.value)

        # Check for structured logs
        self.assertIn('JSON_LOG:', log_output)
        self.assertIn('"correlation_id": "test-corr-id"', log_output)
        self.assertIn('"chain_name": "dna_batch_chain"', log_output)
        self.assertIn('"outcome": "SUCCESS"', log_output)

    def test_parse_error_enum(self):
        dna = "INVALID_DNA"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as lf:
            ledger = json.load(lf)
            self.assertEqual(ledger[dna]['terminal_outcome'], TerminalOutcome.PARSE_ERROR.value)

if __name__ == '__main__':
    unittest.main()

import os
import json
import unittest
import shutil
import io
import sys
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, DNAStatus

class TestMaintainability(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

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

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG: ')]

        self.assertTrue(len(log_lines) > 0, "No structured logs found")

        for line in log_lines:
            json_str = line.replace('JSON_LOG: ', '')
            log_entry = json.loads(json_str)

            required_keys = ['timestamp', 'correlation_id', 'chain_name', 'step', 'outcome', 'actor_id']
            for key in required_keys:
                self.assertIn(key, log_entry, f"Missing required key '{key}' in log entry")

    def test_canonical_naming_in_output(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        self.assertEqual(len(data), 1)
        self.assertIn('dna_sequence', data[0], "JSON output should use 'dna_sequence' key")
        self.assertNotIn('dna', data[0], "JSON output should NOT use legacy 'dna' key")
        self.assertEqual(data[0]['dna_sequence'], dna)

    def test_dna_status_enum_usage(self):
        # This is more of a code-level check, but we can verify outcomes match enum values
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        outcome = ledger[dna]['terminal_outcome']
        self.assertIn(outcome, [s.value for s in DNAStatus], f"Outcome '{outcome}' not in DNAStatus enum values")

if __name__ == '__main__':
    unittest.main()

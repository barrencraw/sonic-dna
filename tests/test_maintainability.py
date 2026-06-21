import os
import json
import csv
import shutil
import unittest
import io
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
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_maintainability')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_dna_sequence_naming_standard(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check JSON
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertIn('dna_sequence', data[0])
        self.assertNotIn('dna', data[0])

        # Check CSV
        with open(self.csv_output, 'r') as f:
            reader = csv.DictReader(f)
            self.assertIn('dna_sequence', reader.fieldnames)
            self.assertNotIn('dna', reader.fieldnames)
            rows = list(reader)
            self.assertEqual(rows[0]['dna_sequence'], dna)

    def test_structured_logging_format(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr-id", actor_id="test-actor")

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG:')]
        self.assertTrue(len(log_lines) >= 1)

        log_entry = json.loads(log_lines[0].replace('JSON_LOG: ', ''))
        required_fields = ["timestamp", "correlation_id", "chain_name", "step", "outcome"]
        for field in required_fields:
            self.assertIn(field, log_entry)

        self.assertEqual(log_entry["correlation_id"], "test-corr-id")
        self.assertEqual(log_entry["actor_id"], "test-actor")

if __name__ == '__main__':
    unittest.main()

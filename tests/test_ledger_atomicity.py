import os
import json
import csv
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestLedgerAtomicity(unittest.TestCase):
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
        self.backup_folder = os.path.join(self.project_root, 'data_backup_atom')
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

    def test_cumulative_output(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        # 1. First run
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna1)

        # 2. Second run with different DNA
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # Should have BOTH dna1 and dna2
        self.assertEqual(len(data), 2, "Output should be cumulative")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

        # Check CSV as well
        with open(self.csv_output, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        self.assertEqual(len(rows), 2)
        csv_dnas = [row['dna'] for row in rows]
        self.assertIn(dna1, csv_dnas)
        self.assertIn(dna2, csv_dnas)

if __name__ == '__main__':
    unittest.main()

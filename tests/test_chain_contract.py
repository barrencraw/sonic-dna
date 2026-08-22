import os
import json
import shutil
import unittest
from utils.dna_ui import run_batch, load_ledger

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_contract')
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

    def test_happy_path_processing(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        processed = run_batch()
        self.assertEqual(processed, 1)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)
        self.assertEqual(data[0]['dna_sequence'], dna)

        ledger_data = load_ledger(self.ledger_path)
        ledger = ledger_data['ledger']
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')
        self.assertEqual(ledger[dna]['dna'], dna)
        self.assertEqual(ledger[dna]['dna_sequence'], dna)

    def test_idempotency_double_invocation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        processed_first = run_batch()
        self.assertEqual(processed_first, 1)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        processed_second = run_batch()
        self.assertEqual(processed_second, 0)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from utils.dna_ui import run_batch, PersistenceError, AtomicWriteError, DNAStatus

class TestChainContract(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.project_root, 'rules')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

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
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-happy-path")

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        ledger = ledger_data.get('ledger', ledger_data)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], DNAStatus.SUCCESS.value)

    def test_idempotency_double_invocation(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch(correlation_id="test-idempotency-1")
        run_batch(correlation_id="test-idempotency-2")

        with open(self.json_output, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Double invocation should not duplicate output entries")

    def test_persistence_failure(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('os.replace', side_effect=OSError("Disk write error")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-persistence-fail")

if __name__ == '__main__':
    unittest.main()

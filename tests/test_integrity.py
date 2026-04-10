import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain(self):
        # Standard DNA: VOL (Volume) should drain 1
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 99)

    def test_high_complexity_refusal(self):
        # Set low integrity
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 5}, f)

        # High Complexity DNA: TEX (Texture Complexity) with scarcity > 5000
        # TEX (prefix), scarcity (5 digits)
        dna = "TEX06000D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Should be refused, so integrity stays 5
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 5)

        # Should NOT be in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

    def test_maintenance_restoration(self):
        # Set low integrity
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 5}, f)

        # Maintenance DNA: TEX with scarcity < 1000
        dna = "TEX00500D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # 5 + 20 = 25
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 25)

    def test_idempotency_integrity(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 100 -> 99
        run_batch() # Should be dedupe hit, no change

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 99)

if __name__ == '__main__':
    unittest.main()

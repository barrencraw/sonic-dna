import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestSystemIntegrity(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize ledger and integrity
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 10}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_standard_wear(self):
        # VOL08900750712 is a Volume string (Standard wear = -2)
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 8) # 10 - 2

    def test_high_complexity_drain(self):
        # TEX with scarcity < 2000 (Drain = -5)
        # TEX (prefix), scarcity (5 digits), granularity (1 char), layering (4 digits), variation (5 digits), spectral (1 char)
        dna = "TEX01500Z001000100Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 5) # 10 - 5

    def test_maintenance_restoration(self):
        # TEX with scarcity > 8000 (Restore = +10)
        dna = "TEX09000Z001000100Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 20) # 10 + 10

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check that it's NOT in the ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

        # Check integrity remains 0
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 0)

    def test_maintenance_allowed_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        dna = "TEX09000Z001000100Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check that it IS in the ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

        # Check integrity restored to 10
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10)

if __name__ == '__main__':
    unittest.main()

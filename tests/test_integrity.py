import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

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

        # Init state
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_idempotency(self):
        # TEX: scarcity 9000 -> -5 wear
        dna = "TEX09000Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95)

        # Run again - should NOT apply wear again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95, "Wear should only be applied once per DNA string")

    def test_maintenance_restoration(self):
        # Set integrity low
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        # TEX: scarcity 0500 -> +10 restore
        dna = "TEX00500Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 60)

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # High scarcity DNA
        dna_high = "TEX09000Z000000000Z"
        # Maintenance DNA
        dna_maint = "TEX00500Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_high}\n{dna_maint}\n")

        run_batch()

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertNotIn(dna_high, ledger, "High scarcity DNA should be skipped/refused at zero integrity")
        self.assertIn(dna_maint, ledger, "Maintenance DNA should still be processed at zero integrity")

        # Check integrity - should have increased by 10
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10)

if __name__ == '__main__':
    unittest.main()

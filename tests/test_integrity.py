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
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_application(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95) # 100 - 5

    def test_maintenance_restoration(self):
        # Set integrity low
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        # Maintenance DNA: TEX + scarcity > 8000
        # TEX (prefix), scarcity (5 digits), granularity (1 char), layering (4 digits), variation (5 digits), spectral (1 char)
        maintenance_dna = "TEX09000D000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 60) # 50 + 10

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Should NOT be in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

    def test_maintenance_bypass(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        maintenance_dna = "TEX09000D000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()

        # SHOULD be in ledger and integrity should be 10
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(maintenance_dna, ledger)

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10)

    def test_integrity_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        with open(self.integrity_path, 'r') as f:
            i1 = json.load(f)['integrity']

        # Second run same DNA
        run_batch()
        with open(self.integrity_path, 'r') as f:
            i2 = json.load(f)['integrity']

        self.assertEqual(i1, i2, "Integrity should NOT decrease on duplicate DNA")

if __name__ == '__main__':
    unittest.main()

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

        # Initial state
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 100}, f)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_idempotency(self):
        # TEX Scarcity 01000 (< 2000) -> -5 wear
        dna = "TEX01000A010001000A"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 1. First Run
        run_batch()
        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 95)

        # 2. Second Run (Idempotent)
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()
        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 95, "Integrity should NOT drain again for same DNA")

    def test_maintenance_restores_integrity(self):
        # Set integrity low
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 50}, f)

        # TEX Scarcity 09000 (> 8000) -> +10 restoration
        dna = "TEX09000A010001000A"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 60)

    def test_refusal_at_zero(self):
        # Set integrity zero
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        # Non-maintenance DNA
        dna_vol = "VOL08900750712"
        # Maintenance DNA
        dna_maint = "TEX09000A010001000A"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna_vol}\n{dna_maint}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_vol]['terminal_outcome'], 'REFUSAL')
        self.assertEqual(ledger[dna_maint]['terminal_outcome'], 'SUCCESS')

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 10, "Maintenance should still work at zero integrity")

if __name__ == '__main__':
    unittest.main()

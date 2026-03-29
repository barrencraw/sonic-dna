import unittest
import os
import json
import shutil
from utils.integrity_manager import IntegrityManager
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

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initial integrity
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)

        # Initial messages
        with open(os.path.join(self.data_folder, 'system_messages.json'), 'w') as f:
            json.dump({
                "consequence_applied": "Wear applied",
                "refusal_reason": "Refused",
                "next_action_hint": "Maintenance"
            }, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_restoration(self):
        # 1. Standard wear (-2)
        # VOL prefix
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 98)

        # 2. High scarcity TEX wear (-5)
        # TEX scarcity < 2000
        dna_tex_low = "TEX01000A000100001A"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_low + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 93)

        # 3. Maintenance TEX restoration (+10)
        # TEX scarcity > 8000
        dna_tex_high = "TEX09000A000100001A"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_high + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 100) # Capped at 100

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        # Should NOT be in ledger as success (it's a refusal)
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(dna_vol, ledger)

        # Maintenance DNA should still work
        dna_tex_high = "TEX09000A000100001A"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_high + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10) # 0 + 10

    def test_idempotency_no_double_drain(self):
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch() # 100 -> 98
        run_batch() # Should skip, stay at 98

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 98)

if __name__ == '__main__':
    unittest.main()

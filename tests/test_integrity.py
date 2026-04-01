import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.messages_path = os.path.join(self.data_folder, 'system_messages.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize messages
        messages = {
          "consequence_applied": "Integrity adjusted.",
          "refusal_reason": "Refusal.",
          "next_action_hint": "Maintenance required."
        }
        with open(self.messages_path, 'w') as f:
            json.dump(messages, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_maintenance(self):
        # 1. Normal wear
        # Using a Volume DNA
        dna_normal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 98) # 100 - 2

        # 2. Heavy load
        # TEX with scarcity > 8000
        # TEX (prefix), scarcity (5 digits), granularity (Z-A, 1 letter), layering (4 digits), variation (5 digits), spectral (Z-A, 1 letter)
        dna_heavy = "TEX09000D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_heavy + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 93) # 98 - 5

        # 3. Idempotency - should NOT apply wear again
        run_batch()
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 93) # Should remain 93

        # 4. Maintenance DNA
        # TEX with scarcity < 1000
        dna_maint = "TEX00500D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maint + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 100) # 93 + 10, capped at 100

    def test_refusal_at_zero(self):
        # Force integrity to 0
        os.makedirs(os.path.dirname(self.integrity_path), exist_ok=True)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # DNA for Volume (not maintenance)
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        # Should NOT be in ledger
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(dna_vol, ledger)

        # Maintenance DNA should STILL work
        dna_maint = "TEX00500D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maint + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10) # 0 + 10

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna_maint, ledger)

if __name__ == '__main__':
    unittest.main()

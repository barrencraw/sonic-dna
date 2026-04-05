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
            # We want to keep the rules and messages if they were there, but for tests we'll recreate messages
            # and rules folder should be present in project root
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize messages
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "Change: {change}, Integrity: {integrity}",
                "refusal_reason": "Depleted",
                "next_action_hint": "Maintenance required"
            }, f)

        # Initialize integrity at 10
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 10}, f)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_maintenance(self):
        # 1. Normal DNA wear (-2)
        dna_normal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 8) # 10 - 2

        # 2. Maintenance DNA (+10)
        # TEX: scarcity < 1000. Example: TEX00500Z010001000Z (scarcity 500)
        dna_maintenance = "TEX00500Z010001000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maintenance + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 18) # 8 + 10

    def test_heavy_load(self):
        # Heavy Load: TEX scarcity > 8000. Example: TEX09000Z010001000Z (scarcity 9000)
        dna_heavy = "TEX09000Z010001000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_heavy + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 5) # 10 - 5

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        dna_normal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch()

        # Integrity should still be 0
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 0)

        # DNA should NOT be in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna_normal, ledger)

        # But maintenance SHOULD still work
        dna_maintenance = "TEX00500Z010001000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maintenance + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10) # 0 + 10

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna_maintenance, ledger)

    def test_idempotency_no_double_wear(self):
        dna_normal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch() # Integrity 10 -> 8

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 8)

        # Run again with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch()

        # Integrity should STILL be 8
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 8)

if __name__ == '__main__':
    unittest.main()

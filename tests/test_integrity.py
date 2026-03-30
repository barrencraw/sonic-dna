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

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger and 100 integrity
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 100}, f)

        # Create system messages for logs to be happy
        system_msg_path = os.path.join(self.data_folder, 'system_messages.json')
        with open(system_msg_path, 'w') as f:
            json.dump({
                "consequence_applied": "SYSTEM_WEAR: {wear} units. CURRENT_INTEGRITY: {integrity}.",
                "refusal_reason": "INTEGRITY_LEVEL_CRITICAL: Non-maintenance processing suspended.",
                "next_action_hint": "Execute Maintenance DNA (TEX scarcity > 8000) to restore integrity."
            }, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain(self):
        # Volume DNA should drain 2 units
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 98)

        # Idempotency check: re-processing same DNA should NOT drain again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 98, "Should not drain integrity again for deduplicated DNA")

    def test_high_density_wear(self):
        # TEX with scarcity < 2000 should drain 5
        # scarcity 01000
        dna = "TEX01000Z001000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95)

    def test_maintenance_restore(self):
        # Set integrity low manually
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 50}, f)

        # TEX with scarcity > 8000 should restore 10
        # scarcity 09000
        dna = "TEX09000Z001000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 60)

    def test_refusal_at_zero(self):
        # Set integrity zero
        with open(self.integrity_path, 'w') as f:
            json.dump({"integrity": 0}, f)

        # Attempt to process non-maintenance
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Should NOT be in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

        # Integrity should still be 0
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 0)

        # Maintenance DNA should STILL work
        maintenance_dna = "TEX09000Z001000000Z"
        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()

        # Should BE in ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(maintenance_dna, ledger)

        # Integrity should be restored to 10
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 10)

if __name__ == '__main__':
    unittest.main()

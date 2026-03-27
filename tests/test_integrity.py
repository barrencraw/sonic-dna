import os
import json
import shutil
import unittest
import time
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

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize messages
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "Integrity adjusted.",
                "refusal_reason": "System integrity critical.",
                "next_action_hint": "Provide maintenance DNA."
            }, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain(self):
        # Normal DNA (Volume) should drain 2 units
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Initial state: 100
        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 98)

    def test_integrity_maintenance_restoration(self):
        # Maintenance DNA (TEX scarcity > 8000) should restore 10 units
        # Let's set integrity to 50 first
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        # TEX scarcity 9000
        dna = "TEX09000A010005000A"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 60)

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Normal DNA should be refused
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Integrity remains 0
        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 0)

        # Ledger should NOT contain the refused DNA
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(dna, ledger)

    def test_maintenance_bypass_refusal(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Maintenance DNA should bypass refusal and restore integrity
        dna = "TEX09000A010005000A"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 10)

        # Ledger SHOULD contain it
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

if __name__ == '__main__':
    unittest.main()

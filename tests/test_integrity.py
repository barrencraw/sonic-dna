import os
import json
import shutil
import unittest
from utils.integrity import IntegrityManager
from utils.dna_ui import main as run_batch

class TestIntegritySystem(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')
        self.messages_path = os.path.join(self.data_folder, 'system_messages.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Create system_messages.json
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "Wear {change}. Integrity {integrity}%.",
                "refusal_reason": "Refused {integrity}%.",
                "next_action_hint": "Hint."
            }, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_wear(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Initial is 100, wear is 5
        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95)

    def test_integrity_refusal_at_zero(self):
        # Force integrity to 0
        os.makedirs(os.path.dirname(self.integrity_path), exist_ok=True)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'refused')

    def test_maintenance_restores_integrity(self):
        # Force integrity to 50
        os.makedirs(os.path.dirname(self.integrity_path), exist_ok=True)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        # TEX DNA with scarcity < 1000 (Maintenance)
        maintenance_dna = "TEX00500A000100001Z"

        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        # Maintenance restores 20
        self.assertEqual(data['integrity'], 70)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[maintenance_dna]['terminal_outcome'], 'success: maintenance')

    def test_recovery_from_zero_integrity(self):
        # Force integrity to 0
        os.makedirs(os.path.dirname(self.integrity_path), exist_ok=True)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # TEX DNA with scarcity < 1000 (Maintenance)
        maintenance_dna = "TEX00500A000100001Z"

        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        # Should recover from 0 to 20
        self.assertEqual(data['integrity'], 20)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[maintenance_dna]['terminal_outcome'], 'success: maintenance')

    def test_idempotency_cross_check(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Integrity 100 -> 95
        run_batch() # Should be dedupe hit, integrity stays 95

        with open(self.integrity_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['integrity'], 95)

if __name__ == '__main__':
    unittest.main()

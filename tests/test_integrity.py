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

        # Create system messages
        with open(self.messages_path, 'w') as f:
            json.dump({
                "consequence_applied": "DRAINED",
                "refusal_reason": "REFUSED",
                "next_action_hint": "HINT"
            }, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain(self):
        # Texture Complexity with layering > 500 (e.g., 0600)
        # TEX (prefix), scarcity (5), granularity (1), layering (4), variation (5), spectral (1)
        dna_drain = "TEX00000Z060000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 90)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna_drain]['terminal_outcome'], 'SUCCESS')

    def test_integrity_restore(self):
        # Initial integrity 50
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        # Texture Complexity with scarcity > 9000 (e.g., 09500)
        dna_restore = "TEX09500Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(dna_restore + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 55)

    def test_integrity_refusal(self):
        # Initial integrity 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Normal DNA (Volume)
        dna_normal = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna_normal]['terminal_outcome'], 'REFUSAL')
        self.assertEqual(ledger[dna_normal]['refusal_info']['reason'], 'REFUSED')

    def test_integrity_idempotency(self):
        # Draining DNA
        dna_drain = "TEX00000Z060000000Z"

        # 1. First run
        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 90)

        # 2. Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            # Should still be 90, not 80
            self.assertEqual(json.load(f)['integrity'], 90)

if __name__ == '__main__':
    unittest.main()

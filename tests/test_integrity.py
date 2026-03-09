import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestSystemIntegrity(unittest.TestCase):
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
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize messages
        self.messages = {
            "consequence_applied": "OPERATIONAL WEAR DETECTED.",
            "refusal_reason": "SYSTEM INTEGRITY DEPLETED.",
            "next_action_hint": "PERFORM MAINTENANCE."
        }
        with open(self.messages_path, 'w') as f:
            json.dump(self.messages, f)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain_and_restore(self):
        # 1. High complexity TEX drains integrity (layering 0600 > 500)
        dna_drain = "TEX05321D060000137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 90)

        # 2. Maintenance TEX restores integrity (scarcity 9500 > 9000)
        dna_restore = "TEX09500D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_restore + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 95)

    def test_refusal_at_zero_integrity(self):
        # 1. Drain integrity to 0
        dna_drain = "TEX05321D060000137Z"
        with open(self.input_file, 'w') as f:
            for _ in range(10):
                # Using unique DNA to bypass ledger if run consecutively
                f.write(f"TEX05321D0600{_ :05d}Z\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 0)

        # 2. Process non-maintenance DNA (should be refused)
        dna_refusal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_refusal + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # Search for refusal entry
        refusal_entry = next(entry for entry in data if entry['dna'] == dna_refusal)
        self.assertEqual(refusal_entry['outcome'], 'REFUSAL')
        self.assertEqual(refusal_entry['reason'], self.messages['refusal_reason'])

    def test_maintenance_always_allowed(self):
        # 1. Force integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # 2. Maintenance DNA should still work
        dna_restore = "TEX09500D007600137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_restore + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        restore_entry = next(entry for entry in data if entry['dna'] == dna_restore)
        self.assertIn('parsed', restore_entry)

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 5)

    def test_integrity_idempotency(self):
        # 1. Processing the same drain DNA twice should only drain once
        dna_drain = "TEX05321D060000137Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")

        run_batch() # First run: drain 10 -> 90

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 90)

        # Re-queue same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_drain + "\n")

        run_batch() # Second run: should dedupe via ledger and NOT drain again

        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 90, "Should NOT have drained integrity a second time for same DNA")

if __name__ == '__main__':
    unittest.main()

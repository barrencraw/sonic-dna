import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch
from utils.integrity_manager import IntegrityManager

class TestIntegrity(unittest.TestCase):
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

        # Start with fresh 100 integrity
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)

        # Start with empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        # Re-create system_messages.json in fresh data folder
        sys_msg_path = os.path.join(self.data_folder, 'system_messages.json')
        with open(sys_msg_path, 'w') as f:
            json.dump({
                "consequence_applied": "Wear noted.",
                "refusal_reason": "Integrity at 0.",
                "next_action_hint": "Maintenance required."
            }, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_wear_and_restoration(self):
        # 1. Standard wear (-2)
        # VOL08900750712 is Volume DNA
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch()
        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 98)

        # 2. High wear (-5)
        # TEX01000Z000200000Z: Scarcity=1000 (< 2000)
        dna_tex_high = "TEX01000Z000200000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_high + "\n")
        run_batch()
        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 93)

        # 3. Restoration (+10)
        # TEX09000Z000200000Z: Scarcity=9000 (> 8000)
        dna_tex_maint = "TEX09000Z000200000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_maint + "\n")
        run_batch()
        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 100) # Capped at 100

    def test_refusal_at_zero(self):
        # Set integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Try to process non-maintenance DNA
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch()

        # Check that it's NOT in the ledger and NOT in JSON output
        with open(self.ledger_path, 'r') as f:
            self.assertNotIn(dna_vol, json.load(f))

        json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        if os.path.exists(json_output):
            with open(json_output, 'r') as f:
                self.assertEqual(len(json.load(f)), 0)

        # Try to process maintenance DNA (should work)
        dna_tex_maint = "TEX09000Z000200000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_tex_maint + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 10)
        with open(self.ledger_path, 'r') as f:
            self.assertIn(dna_tex_maint, json.load(f))

    def test_wear_idempotency(self):
        # Ensure wear is applied exactly once per DNA string
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # 100 -> 98

        # Re-run same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # Should be skipped, no wear

        with open(self.integrity_path, 'r') as f:
            self.assertEqual(json.load(f)['integrity'], 98)

if __name__ == '__main__':
    unittest.main()

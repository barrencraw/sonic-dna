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
        self.integrity_file = os.path.join(self.data_folder, 'system_integrity.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            # We want to keep system_messages.json if it exists, or re-create it
            # Actually, let's just restore it after wipe if we have it in backup
            msgs = None
            msg_path = os.path.join(self.data_folder, 'system_messages.json')
            if os.path.exists(msg_path):
                with open(msg_path, 'r') as f:
                    msgs = f.read()

            shutil.rmtree(self.data_folder)
            os.makedirs(self.raw_folder, exist_ok=True)
            os.makedirs(self.output_folder, exist_ok=True)

            if msgs:
                with open(os.path.join(self.data_folder, 'system_messages.json'), 'w') as f:
                    f.write(msgs)
        else:
            os.makedirs(self.raw_folder, exist_ok=True)
            os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain_and_refusal(self):
        # 1. Start with 100 integrity
        with open(self.integrity_file, 'w') as f:
            json.dump({'integrity': 4}, f) # Set low for quick test

        # Normal DNA (VOL) - wear is -2
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        dna3 = "VOL11111111111"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n{dna3}\n")

        run_batch()

        # dna1 should succeed (4 -> 2)
        # dna2 should succeed (2 -> 0)
        # dna3 should be REFUSED (0)

        with open(self.integrity_file, 'r') as f:
            integrity = json.load(f)['integrity']
        self.assertEqual(integrity, 0)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna1, ledger)
        self.assertIn(dna2, ledger)
        self.assertNotIn(dna3, ledger) # Refused DNA is not in ledger

    def test_maintenance_restoration(self):
        # 1. Start with 0 integrity
        with open(self.integrity_file, 'w') as f:
            json.dump({'integrity': 0}, f)

        # Maintenance DNA: TEX with scarcity > 9000
        # Prefix TEX, scarcity 9500 (5 digits -> 09500)
        # granularity Z, layering 0000, variation 00000, spectral Z
        maint_dna = "TEX09500Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(maint_dna + "\n")

        run_batch()

        with open(self.integrity_file, 'r') as f:
            integrity = json.load(f)['integrity']
        self.assertEqual(integrity, 10) # 0 + 10

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(maint_dna, ledger)

    def test_heavy_wear(self):
        with open(self.integrity_file, 'w') as f:
            json.dump({'integrity': 100}, f)

        # Heavy wear: TEX with scarcity < 2000
        heavy_dna = "TEX01000Z000000000Z"

        with open(self.input_file, 'w') as f:
            f.write(heavy_dna + "\n")

        run_batch()

        with open(self.integrity_file, 'r') as f:
            integrity = json.load(f)['integrity']
        self.assertEqual(integrity, 95) # 100 - 5

    def test_integrity_idempotency(self):
        # Ensure double-processing same DNA doesn't double-drain
        with open(self.integrity_file, 'w') as f:
            json.dump({'integrity': 100}, f)

        dna = "VOL08900750712"

        # First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.integrity_file, 'r') as f:
            integrity1 = json.load(f)['integrity']
        self.assertEqual(integrity1, 98)

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.integrity_file, 'r') as f:
            integrity2 = json.load(f)['integrity']
        self.assertEqual(integrity2, 98, "Integrity should NOT drain on duplicate DNA")

if __name__ == '__main__':
    unittest.main()

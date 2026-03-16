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

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_integrity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Start with 100 integrity
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)

        # Empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain_standard(self):
        # VOL DNA should drain 2
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 98)

    def test_integrity_drain_high_complexity(self):
        # TEX Scarcity < 2000 should drain 5
        # TEX (prefix), scarcity (5 digits)
        dna = "TEX01000Z000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 95)

    def test_integrity_restore_maintenance(self):
        # TEX Scarcity > 8000 should restore 10
        # First drain some
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 50}, f)

        dna = "TEX09000Z000000000Z"
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

        # Try to process non-maintenance DNA
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertTrue(ledger[dna]['terminal_outcome'].startswith("REFUSAL"))

        # Try to process maintenance DNA
        dna_maint = "TEX09500Z000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(dna_maint + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger[dna_maint]['terminal_outcome'], "SUCCESS")

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 10)

    def test_idempotency_no_double_drain(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # Drain 2 -> 98
        run_batch() # Should be deduplicated, no further drain

        with open(self.integrity_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['integrity'], 98)

if __name__ == '__main__':
    unittest.main()

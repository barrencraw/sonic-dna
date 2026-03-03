import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch
from utils.system_integrity import get_integrity, apply_integrity_delta

class TestSystemFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_file = os.path.join(self.data_folder, 'system_integrity.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Reset Integrity to 100
        apply_integrity_delta(100.0)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_drain_and_recovery(self):
        # 1. High complexity drains integrity
        # TEX: scarcity 00000, granularity A, layering 1000, variation 10000, spectral A
        drain_dna = "TEX00000A100010000A"
        with open(self.input_file, 'w') as f:
            f.write(drain_dna + "\n")

        initial = get_integrity()
        run_batch()
        after_drain = get_integrity()
        self.assertTrue(after_drain < initial, f"Integrity should have drained. {initial} -> {after_drain}")
        self.assertEqual(after_drain, initial - 10.0)

        # 2. Maintenance restores integrity
        # TEX: scarcity 10000, granularity Z, layering 0000, variation 00000, spectral Z
        maintenance_dna = "TEX10000Z000000000Z"
        with open(self.input_file, 'w') as f:
            f.write(maintenance_dna + "\n")

        run_batch()
        after_recovery = get_integrity()
        self.assertTrue(after_recovery > after_drain, "Integrity should have recovered.")
        # Recovery is 15.0, but capped at 100.0
        expected = min(100.0, after_drain + 15.0)
        self.assertEqual(after_recovery, expected)

    def test_refusal_at_zero_integrity(self):
        # Force integrity to 0
        apply_integrity_delta(-100.0)
        self.assertEqual(get_integrity(), 0.0)

        drain_dna = "TEX00000A100010000A"
        with open(self.input_file, 'w') as f:
            f.write(drain_dna + "\n")

        run_batch()

        # Check that it was NOT processed (not in ledger or output)
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(drain_dna, ledger)

        # Integrity should still be 0
        self.assertEqual(get_integrity(), 0.0)

    def test_idempotency_no_double_drain(self):
        dna = "VOL08900750712" # Baseline drain -1.0
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        integrity1 = get_integrity()

        # Run again with same DNA
        run_batch()
        integrity2 = get_integrity()

        self.assertEqual(integrity1, integrity2, "Integrity should not drain twice for the same DNA string.")

if __name__ == '__main__':
    unittest.main()

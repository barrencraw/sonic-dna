import unittest
import os
import json
import shutil
import tempfile
from utils.integrity import IntegrityManager
from utils.dna_calculator import DNACalculator

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.integrity_path = os.path.join(self.test_dir, 'system_integrity.json')
        self.mgr = IntegrityManager(self.integrity_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_initial_integrity(self):
        self.assertEqual(self.mgr.integrity, 100)

    def test_apply_wear_standard(self):
        # Standard DNA (not Texture Complexity)
        dna_result = {'rule': 'Volume', 'values': {'amp': 800}}
        change = self.mgr.apply_wear(dna_result)
        self.assertEqual(change, -1)
        self.assertEqual(self.mgr.integrity, 99)

    def test_apply_wear_high_complexity(self):
        # High-Complexity (TEX scarcity > 5000)
        dna_result = {'rule': 'Texture Complexity', 'values': {'scarcity': 6000}}
        change = self.mgr.apply_wear(dna_result)
        self.assertEqual(change, -5)
        self.assertEqual(self.mgr.integrity, 95)

    def test_apply_wear_maintenance(self):
        # Maintenance (TEX scarcity < 1000)
        self.mgr.integrity = 50
        dna_result = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        change = self.mgr.apply_wear(dna_result)
        self.assertEqual(change, 20)
        self.assertEqual(self.mgr.integrity, 70)

    def test_can_process_refusal(self):
        self.mgr.integrity = 5
        high_comp = {'rule': 'Texture Complexity', 'values': {'scarcity': 6000}}
        standard = {'rule': 'Volume', 'values': {'amp': 800}}
        maintenance = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}

        self.assertFalse(self.mgr.can_process(high_comp))
        self.assertTrue(self.mgr.can_process(standard))
        self.assertTrue(self.mgr.can_process(maintenance))

    def test_can_process_zero_integrity(self):
        self.mgr.integrity = 0
        standard = {'rule': 'Volume', 'values': {'amp': 800}}
        maintenance = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}

        self.assertFalse(self.mgr.can_process(standard))
        self.assertTrue(self.mgr.can_process(maintenance))

    def test_persistence_atomic(self):
        self.mgr.integrity = 80
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.mgr.save(target_dir=tmp_dir)

            # Verify file exists at final destination
            self.assertTrue(os.path.exists(self.integrity_path))
            with open(self.integrity_path, 'r') as f:
                data = json.load(f)
                self.assertEqual(data['integrity'], 80)

class TestIntegrityIntegration(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.integrity_path = os.path.join(self.data_folder, 'system_integrity.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_int')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Fresh integrity (100)
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 100}, f)
        # Fresh ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_integrity_idempotency(self):
        """Prove that integrity is only drained once for the same DNA string."""
        from utils.dna_ui import main as run_batch
        dna = "VOL08900750712" # Cost -1

        # 1. First run
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            int1 = json.load(f)['integrity']
        self.assertEqual(int1, 99)

        # 2. Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.integrity_path, 'r') as f:
            int2 = json.load(f)['integrity']
        self.assertEqual(int2, 99, "Integrity should NOT drain again for already processed DNA")

if __name__ == '__main__':
    unittest.main()

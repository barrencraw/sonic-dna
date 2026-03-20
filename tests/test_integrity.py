import unittest
import os
import json
import shutil
import tempfile
from utils.integrity_manager import IntegrityManager
from utils.dna_ui import main as run_batch

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.integrity_path = os.path.join(self.data_dir, 'system_integrity.json')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        # Mocking os.getcwd to use test_dir
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create rules folder link or copy
        rules_src = os.path.join(self.old_cwd, 'rules')
        rules_dst = os.path.join(self.test_dir, 'rules')
        shutil.copytree(rules_src, rules_dst)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_integrity_drain_and_restoration(self):
        manager = IntegrityManager(self.integrity_path)
        self.assertEqual(manager.integrity, 100)

        # High complexity (scarcity < 2000) -> drain 5
        new_integrity = manager.calculate_new_integrity(manager.integrity, {'rule': 'Texture Complexity', 'values': {'scarcity': 1000}})
        self.assertEqual(new_integrity, 95)

        # Maintenance (scarcity > 8000) -> restore 10
        new_integrity = manager.calculate_new_integrity(90, {'rule': 'Texture Complexity', 'values': {'scarcity': 9000}})
        self.assertEqual(new_integrity, 100) # Capped at 100

        # Drain to 0
        integrity = 100
        for _ in range(20):
            integrity = manager.calculate_new_integrity(integrity, {'rule': 'Texture Complexity', 'values': {'scarcity': 1000}})
        self.assertEqual(integrity, 0)

    def test_refusal_and_idempotency(self):
        # 1. Drain integrity to 0
        with open(self.integrity_path, 'w') as f:
            json.dump({'integrity': 0}, f)

        # 2. Try to process non-maintenance DNA
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # 3. Verify it was REFUSED and NOT in ledger
        if os.path.exists(self.ledger_path):
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(dna, ledger)

        # 4. Process maintenance DNA
        with open(self.input_file, 'a') as f:
            f.write("TEX09000Z000000000Z\n") # TEX scarcity 9000

        run_batch()

        # 5. Verify maintenance DNA was processed and integrity restored
        with open(self.integrity_path, 'r') as f:
            integrity_data = json.load(f)
        self.assertEqual(integrity_data['integrity'], 10)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn("TEX09000Z000000000Z", ledger)
        self.assertEqual(ledger["TEX09000Z000000000Z"]["terminal_outcome"], "SUCCESS")

if __name__ == '__main__':
    unittest.main()

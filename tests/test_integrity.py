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
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup data folders
        os.makedirs('data/raw')
        os.makedirs('data/output')

        # Link or copy rules (minimal copy for test)
        os.makedirs('rules')
        # We only need Texture Complexity for this test
        src_rules = os.path.join(self.old_cwd, 'rules', 'rules_Texture_Complexity.json')
        shutil.copy(src_rules, 'rules/')

        # Integrity state path
        self.integrity_path = 'data/system_integrity.json'

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open('data/raw/toSequence.txt', 'w') as f:
            for dna in dna_list:
                f.write(dna + '\n')

    def get_integrity(self):
        if not os.path.exists(self.integrity_path):
            return 100
        with open(self.integrity_path, 'r') as f:
            return json.load(f)['integrity']

    def test_integrity_wear_and_maintenance(self):
        # 1. Start with 100
        self.assertEqual(self.get_integrity(), 100)

        # 2. Process high-density DNA (scarcity < 2000)
        # TEX01000Z000000000Z: scarcity=1000 (<2000), granularity=Z, layering=0000, variation=00000, spectral=Z
        self.write_dna(['TEX01000Z000000000Z'])
        run_batch()
        self.assertEqual(self.get_integrity(), 95) # 100 - 5

        # 3. Process maintenance DNA (scarcity > 8000)
        # TEX09000Z000000000Z: scarcity=9000 (>8000)
        self.write_dna(['TEX09000Z000000000Z'])
        run_batch()
        self.assertEqual(self.get_integrity(), 100) # 95 + 10 (capped at 100)

        # 4. Drain to zero
        # 20 strings of high-density DNA (each -5)
        # We need 20 NEW strings.
        dna_list = [f'TEX{1000+i:05d}Z000000000Z' for i in range(21)] # 21 strings to be sure
        self.write_dna(dna_list)
        run_batch()
        self.assertEqual(self.get_integrity(), 0)

        # 5. Verify refusal
        # High-density DNA should be refused
        refused_dna = 'TEX00500Z000000000Z'
        self.write_dna([refused_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 0)
        # Verify it wasn't added to output or ledger
        if os.path.exists('data/processed_ledger.json'):
            with open('data/processed_ledger.json', 'r') as f:
                ledger = json.load(f)
            self.assertNotIn(refused_dna, ledger)

        # 6. Maintenance still works at 0
        maintenance_dna = 'TEX09500Z000000000Z'
        self.write_dna([maintenance_dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 10)
        with open('data/processed_ledger.json', 'r') as f:
            ledger = json.load(f)
        self.assertIn(maintenance_dna, ledger)

    def test_idempotency_no_silent_drains(self):
        # 1. Process one DNA
        dna = 'TEX01000Z000000000Z'
        self.write_dna([dna])
        run_batch()
        self.assertEqual(self.get_integrity(), 95)

        # 2. Process same DNA again
        # It should hit idempotency and NOT drain integrity again
        run_batch()
        self.assertEqual(self.get_integrity(), 95)

if __name__ == '__main__':
    unittest.main()

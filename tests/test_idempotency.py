import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as dna_main

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Mock project structure for rules
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        shutil.copytree('rules', self.rules_dir)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_deduplication(self):
        # 1. Write same DNA twice
        dna = "VOL08900750712"
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            f.write(f"{dna}\n{dna}\n")

        # 2. Run batch
        dna_main()

        # 3. Verify ledger has 1 entry
        ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(len(ledger), 1)

    def test_double_invocation_same_key(self):
        dna = "VOL08900750712"
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        # First run
        with open(input_file, 'w') as f:
            f.write(f"{dna}\n")
        dna_main()

        # Second run with same DNA
        with open(input_file, 'w') as f:
            f.write(f"{dna}\n")
        dna_main()

        # Verify ledger
        ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
        # We expect SUCCESS in uppercase now as per Outcome Enum
        self.assertEqual(ledger[dna]['terminal_outcome'], 'SUCCESS')

if __name__ == '__main__':
    unittest.main()

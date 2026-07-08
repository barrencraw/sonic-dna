import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.project_root, 'rules')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data/rules if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        self.rules_backup = os.path.join(self.project_root, 'rules_backup')
        if os.path.exists(self.rules_folder):
            shutil.copytree(self.rules_folder, self.rules_backup, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        if not os.path.exists(self.rules_folder):
            os.makedirs(self.rules_folder)

        # Ensure rules_Volume.json exists for tests
        self.rule_file = os.path.join(self.rules_folder, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

        if os.path.exists(self.rules_folder):
            shutil.rmtree(self.rules_folder)
        if os.path.exists(self.rules_backup):
            shutil.move(self.rules_backup, self.rules_folder)

    def test_double_invocation_same_key(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL089"

        # 1. First invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna'], dna)

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)
        self.assertEqual(ledger[dna]['terminal_outcome'], 'success')

        # 2. Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Verify no duplicate entry in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL089"
        dna2 = "VOL000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        # It should process dna1 (once) and dna2 (once)
        self.assertEqual(len(data), 2, "Should have exactly 2 entries")
        dnas = [entry['dna'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

if __name__ == '__main__':
    unittest.main()

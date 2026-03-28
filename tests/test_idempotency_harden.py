import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch

class TestIdempotencyHarden(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock a rule file
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_double_invocation_same_key(self):
        dna = "VOL08900750712"

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

        # 2. Second invocation with same DNA (double-invoke scenario)
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Verify no duplicate entry in cumulative output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_multiple_mixed_dnas(self):
        dna1 = "VOL001"
        dna2 = "VOL002"

        # First run: process dna1
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")
        run_batch()

        # Second run: process dna1 and dna2
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Total entries should be 2 (dna1, then dna2)
        self.assertEqual(len(data), 2)
        dnas = [entry['dna'] for entry in data]
        self.assertEqual(dnas, [dna1, dna2])

if __name__ == '__main__':
    unittest.main()

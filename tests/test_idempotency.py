import os
import json
import shutil
import unittest
import time
import tempfile
from utils.dna_ui import main as run_batch

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(self.rules_folder, exist_ok=True)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Create a real rule for Volume
        with open(os.path.join(self.rules_folder, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"},
                    "lr": {"min": 0, "max": 100, "pad": 3, "description": "lr"},
                    "sur": {"min": 0, "max": 10, "pad": 2, "description": "sur"},
                    "head": {"min": 0, "max": 60, "pad": 2, "description": "head"}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_double_invocation_same_key(self):
        # DNA for Volume (prefix 'VOL')
        dna = "VOL08900750712"

        # 1. First invocation
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(base_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['dna_sequence'], dna)

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertIn(dna, state['ledger'])
        self.assertEqual(state['ledger'][dna]['terminal_outcome'], 'success')

        # 2. Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(base_dir=self.test_dir)

        # Verify no duplicate entry in output
        with open(self.json_output, 'r') as f:
            data = json.load(f)
        self.assertEqual(len(data), 1, "Should NOT have added a second entry for the same DNA")

    def test_mixed_duplicates(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        # Note: dna1 is provided twice in the SAME batch.
        # utils/dna_ui.py DOES NOT currently do intra-batch de-duplication
        # unless it checks the ledger during the loop.
        # Let's see if we should add intra-batch de-dupe.

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        run_batch(base_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # If it doesn't do intra-batch de-dupe, it will have 3 entries.
        # But the contract says "Multiple invocations of the same DNA string do not create duplicate entries".
        # This should probably apply to the same batch too.

        self.assertEqual(len(data), 2, f"Should have exactly 2 entries, got {len(data)}")
        dnas = [entry['dna_sequence'] for entry in data]
        self.assertIn(dna1, dnas)
        self.assertIn(dna2, dnas)

if __name__ == '__main__':
    unittest.main()

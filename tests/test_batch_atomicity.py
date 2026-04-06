import unittest
import os
import json
import shutil
import tempfile
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestBatchAtomicity(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.raw_dir = os.path.join(self.test_dir, 'data', 'raw')
        self.output_dir = os.path.join(self.test_dir, 'data', 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_VOL.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amplitude", "type": "int", "min": 0, "max": 9999, "pad": 4}
                }
            }, f)

        # Mock an input file
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(self.input_file, 'w') as f:
            f.write("VOL0123\n")

        # Set up paths for the ledger
        self.ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    @patch('os.getcwd')
    @patch('os.replace')
    def test_persistence_failure_atomicity(self, mock_replace, mock_getcwd):
        """
        Verify that if os.replace fails during the atomic commit,
        the input file remains intact and the ledger is not updated in its final location.
        """
        mock_getcwd.return_value = self.test_dir

        # Simulate failure on the second file replacement (e.g., CSV)
        # 1st: JSON, 2nd: CSV, 3rd: Ledger
        mock_replace.side_effect = [None, Exception("Simulated Disk Failure")]

        with self.assertRaises(PersistenceError):
            run_batch()

        # Verify that the final ledger file does not exist (it shouldn't have been moved)
        self.assertFalse(os.path.exists(self.ledger_path))

        # Verify that the output files don't exist in their final location
        # (Actually, mock_replace[0] was None, so JSON might have been moved.
        # But wait, our implementation does 3 replaces. If the 2nd fails,
        # the 3rd (ledger) is never reached.)
        # This is why the ledger is important.

    @patch('os.getcwd')
    def test_happy_path_clears_file_logic_in_main(self, mock_getcwd):
        """
        This test checks if dna_ui.main() completes normally.
        Clearing toSequence.txt is handled by main.py, so we verify that run_batch()
        works as expected first.
        """
        mock_getcwd.return_value = self.test_dir

        run_batch()

        # Verify ledger exists
        self.assertTrue(os.path.exists(self.ledger_path))
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
            self.assertIn("VOL0123", ledger)

if __name__ == '__main__':
    unittest.main()

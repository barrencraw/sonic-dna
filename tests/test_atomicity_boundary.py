import os
import json
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicity(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_atomicity')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initial state
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.json_output, 'w') as f:
            json.dump([], f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_atomic_write_failure_preserves_state(self):
        """
        Verify that if os.replace fails mid-way (simulated), the system doesn't leave
        inconsistent state. Note: In reality, if it fails after 1 rename but before 3,
        we might have partial success. But the goal of the atomic block is to
        minimise this window and ensure that we don't clear input if it fails.
        """
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock os.replace to fail on the second call
        original_replace = os.replace
        call_count = 0

        def side_effect_replace(src, dst):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("Simulated Failure during atomic move")
            return original_replace(src, dst)

        with patch('os.replace', side_effect=side_effect_replace):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Verify that despite failure, the input file was NOT cleared by main.py's watcher logic
        # (Though run_batch itself doesn't clear it, the caller does if it succeeds)

        # Verify ledger wasn't updated in the final location if it was the 3rd rename
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertNotIn(dna, ledger)

    def test_all_or_nothing_success(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # All files should exist
        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.csv_output))
        self.assertTrue(os.path.exists(self.ledger_path))

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

if __name__ == '__main__':
    unittest.main()

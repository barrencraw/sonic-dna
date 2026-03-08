import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import csv
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestDNABatchHardened(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_input(self, dna_strings):
        with open(self.input_file, 'w') as f:
            for s in dna_strings:
                f.write(f"{s}\n")

    def test_cumulative_and_idempotency(self):
        """Verify that multiple runs append data and skip already processed strings."""
        # First run
        self.write_input(["V100", "V200"])
        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['dna'], 'V100')
            self.assertEqual(data[1]['dna'], 'V200')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn("V100", ledger)
            self.assertIn("V200", ledger)

        # Second run with one new and one duplicate
        self.write_input(["V200", "V300"])
        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 3, "Should have 3 unique entries in total")
            self.assertEqual(data[2]['dna'], 'V300')

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(len(ledger), 3)
            self.assertIn("V300", ledger)

    def test_ledger_as_source_of_truth_on_partial_failure(self):
        """Verify that if persistence fails partially, the ledger remains the source of truth and zombies are cleaned up."""
        # Initial successful run
        self.write_input(["V100"])
        run_batch()

        # Confirm initial state
        with open(self.ledger_file, 'r') as f:
            initial_ledger = json.load(f)

        # Second run that will fail during atomic write (after JSON is replaced but before CSV/Ledger)
        self.write_input(["V200"])

        # We'll mock os.replace to fail on the second file (CSV)
        original_replace = os.replace
        def side_effect(src, dst):
            if 'toSequence_parsed.csv' in dst:
                raise OSError("Atomic Commit Failed")
            return original_replace(src, dst)

        with patch('os.replace', side_effect=side_effect):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Verify ledger is UNCHANGED
        with open(self.ledger_file, 'r') as f:
            current_ledger = json.load(f)
            self.assertEqual(initial_ledger, current_ledger, "Ledger should NOT have been updated")

        # Verify JSON has the zombie (because it was replaced before CSV failure in our mock)
        with open(self.json_out, 'r') as f:
            data = json.load(f)
            # The count depends on order of os.replace calls in main()
            # If JSON was first, it's 2.
            self.assertEqual(len(data), 2, "JSON should have the zombie entry")

        # THIRD RUN: Successful processing of V200. It should clean up the zombie.
        self.write_input(["V200"])
        run_batch()

        with open(self.json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 2, "Final JSON should have exactly 2 entries (V100, V200)")
            dnas = [item.get('dna') for item in data]
            self.assertIn('V100', dnas)
            self.assertIn('V200', dnas)
            self.assertEqual(dnas.count('V200'), 1, "Should NOT have duplicate V200 despite zombie")

    def test_observability_logs(self):
        """Verify that observability and idempotency logs are emitted."""
        self.write_input(["V100"])

        with patch('sys.stdout', new_callable=MagicMock) as mock_stdout:
            run_batch()

            # Extract all printed messages
            output = "\n".join([call.args[0] for call in mock_stdout.write.call_args_list if call.args])

            self.assertIn("[OBSERVABILITY]", output)
            self.assertIn("step=start", output)
            self.assertIn("step=terminal", output)
            self.assertIn("outcome=success", output)
            self.assertIn("[Idempotency]", output)
            self.assertIn("dedupe_hit=False", output)

if __name__ == '__main__':
    unittest.main()

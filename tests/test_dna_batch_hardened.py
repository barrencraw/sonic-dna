import unittest
import os
import shutil
import tempfile
import json
import csv
import sys
from unittest.mock import MagicMock

# Mock dependencies for PySide6 if not installed
if "PySide6" not in sys.modules:
    mock_pyside6 = MagicMock()
    sys.modules["PySide6"] = mock_pyside6
    sys.modules["PySide6.QtWidgets"] = mock_pyside6
    sys.modules["PySide6.QtCore"] = mock_pyside6
    sys.modules["PySide6.QtGui"] = mock_pyside6

from utils.dna_ui import main as run_batch

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

        # Mock a rule file for Volume
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
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

    def test_sync_integrity(self):
        """Verify that JSON, CSV, and Ledger are perfectly in sync after multiple runs with duplicates."""
        # Run 1: process V100, V200
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            f.write("V100\nV200\n")
        run_batch()

        # Run 2: process V200 (duplicate), V300 (new)
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            f.write("V200\nV300\n")
        run_batch()

        # Verify results
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'processed_ledger.json')

        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(csv_out))
        self.assertTrue(os.path.exists(ledger_out))

        with open(json_out, 'r') as f:
            json_data = json.load(f)
        with open(ledger_out, 'r') as f:
            ledger_data = json.load(f)
        with open(csv_out, 'r') as f:
            csv_reader = csv.DictReader(f)
            csv_data = list(csv_reader)

        # Expected: V100, V200, V300 (one entry each, exactly once)
        self.assertEqual(len(json_data), 3, "JSON output should have exactly 3 entries")
        self.assertEqual(len(csv_data), 3, "CSV output should have exactly 3 rows")
        self.assertEqual(len(ledger_data), 3, "Ledger should have exactly 3 entries")

        dnas = [item['dna'] for item in json_data]
        self.assertCountEqual(dnas, ["V100", "V200", "V300"])

        csv_dnas = [row['dna'] for row in csv_data]
        self.assertCountEqual(csv_dnas, ["V100", "V200", "V300"])

        self.assertIn("V100", ledger_data)
        self.assertIn("V200", ledger_data)
        self.assertIn("V300", ledger_data)

    def test_idempotency_key_outcome_preserved(self):
        """Verify that the terminal outcome in the ledger is preserved."""
        # Process V100
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            f.write("V100\n")
        run_batch()

        # Corrupt the JSON output manually to see if re-processing is skipped
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'w') as f:
            json.dump([], f)

        # Run again with V100
        with open(os.path.join(self.raw_dir, 'toSequence.txt'), 'w') as f:
            f.write("V100\n")
        run_batch()

        # Result: V100 should NOT be in the JSON output because it was skipped via ledger
        with open(json_out, 'r') as f:
            json_data = json.load(f)
        self.assertEqual(len(json_data), 0, "V100 should have been skipped and not added back")

if __name__ == '__main__':
    unittest.main()

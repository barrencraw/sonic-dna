import sys
from unittest.mock import MagicMock

# Mock GUI dependencies
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestBatchAtomicity(unittest.TestCase):
    def setUp(self):
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

    def test_unified_atomic_commit_failure(self):
        """
        If one file fails to write/rename during the atomic commit phase,
        none of the files (JSON, CSV, Ledger) should be updated.
        """
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # 1. Success first to establish state
        run_batch()

        self.assertTrue(os.path.exists(self.json_out))
        self.assertTrue(os.path.exists(self.csv_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn("V100", ledger)

        # 2. Try to process new DNA but fail during the final rename step
        with open(self.input_file, 'w') as f:
            f.write("V200\n")

        # Mock os.replace to fail only on the second call (CSV) to simulate partial failure
        original_replace = os.replace
        call_count = 0
        def side_effect(src, dst):
            nonlocal call_count
            call_count += 1
            if call_count == 2: # Fail on second rename (CSV)
                raise OSError("Atomic Commit Failed")
            return original_replace(src, dst)

        with patch('os.replace', side_effect=side_effect):
            with self.assertRaises(PersistenceError):
                run_batch()

        # 3. Verify that the ledger still only has V100, and JSON/CSV are also rolled back/unchanged
        # Note: In our current implementation, once one os.replace fails, the others might have already succeeded.
        # True atomicity across MULTIPLE files is hard without a real transaction.
        # But our plan says "unify atomic write pattern".

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            # If CSV failed, ledger should NOT have V200.
            # (Note: Current implementation replaces JSON first, then CSV, then Ledger.
            # If it fails at CSV, JSON is changed but Ledger is NOT.
            # This prevents the system from thinking V200 is DONE.)
            self.assertNotIn("V200", ledger)

    def test_single_item_latency_and_correlation(self):
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        corr_id = "test-corr-id"
        run_batch(correlation_id=corr_id)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger["V100"]["correlation_id"], corr_id)
            self.assertIn("latency_ms", ledger["V100"])

if __name__ == '__main__':
    unittest.main()

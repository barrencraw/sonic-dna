import unittest
import os
import shutil
import tempfile
import json
import io
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

# Mock dependencies for headless testing
from unittest.mock import MagicMock
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

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

        # Mock a rule file for Volume
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_end_to_end_hardened(self):
        """
        Verifies:
        (a) unique DNA strings are processed once and recorded in the ledger
        (b) duplicate strings are correctly deduplicated
        (d) observability logs are emitted correctly
        """
        dna1 = "VOL100"
        dna2 = "VOL200"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna1}\n{dna2}\n")

        f = io.StringIO()
        with redirect_stdout(f):
            run_batch(correlation_id="test-corr", actor_id="test-actor")

        output = f.getvalue()

        # Check observability logs
        logs = [line for line in output.split('\n') if line.startswith('[OBSERVABILITY]')]
        self.assertTrue(len(logs) >= 4) # start, process_dna(dna1), process_dna(dna1-dedupe), process_dna(dna2), end

        start_log = json.loads(logs[0].replace('[OBSERVABILITY] ', ''))
        self.assertEqual(start_log['step'], 'batch_process_start')
        self.assertEqual(start_log['correlation_id'], 'test-corr')

        # Verify output files
        with open(self.json_out, 'r') as jf:
            data = json.load(jf)
            self.assertEqual(len(data), 2) # Only 2 unique ones
            dnas = [d['dna'] for d in data]
            self.assertIn(dna1, dnas)
            self.assertIn(dna2, dnas)

        # Verify ledger
        with open(self.ledger_file, 'r') as lf:
            ledger = json.load(lf)
            self.assertIn(dna1, ledger)
            self.assertIn(dna2, ledger)
            self.assertEqual(ledger[dna1]['terminal_outcome'], 'SUCCESS')

    def test_atomicity_on_failure(self):
        """
        (c) a simulated failure before the atomic rename does not result in partial or torn output files
        """
        dna = "VOL500"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Simulate failure during the atomic write phase
        with patch('os.replace', side_effect=OSError("Atomic Rename Failed")):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Files should not exist or be empty if it was the first run
        self.assertFalse(os.path.exists(self.json_out))
        self.assertFalse(os.path.exists(self.csv_out))
        self.assertFalse(os.path.exists(self.ledger_file))

    def test_ledger_consistency_after_partial_run(self):
        """Verify that only successfully committed batches update the ledger."""
        dna1 = "VOL111"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch() # First batch succeeds

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna1, ledger)

        dna2 = "VOL222"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        # Second batch fails during commit
        with patch('os.replace', side_effect=OSError("Crash")):
            with self.assertRaises(PersistenceError):
                run_batch()

        # Ledger should still only have dna1
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn(dna1, ledger)
            self.assertNotIn(dna2, ledger)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock, patch

# Mock dependencies before any imports
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

import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicityHardened(unittest.TestCase):
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

        with open(self.input_file, 'w') as f:
            f.write("V100\n")

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

    def test_ledger_output_sync(self):
        """Verify that ledger and output files are updated together."""
        run_batch(correlation_id="test-sync")

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        self.assertTrue(os.path.exists(self.ledger_file))

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertEqual(len(data), 1)

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
            self.assertIn("V100", ledger)

    def test_failure_rolls_back_ledger(self):
        """If persistence fails, the ledger should not be updated on disk."""
        # First verify it doesn't exist
        self.assertFalse(os.path.exists(self.ledger_file))

        with patch('os.replace', side_effect=OSError("Atomic Rename Failed")):
            with self.assertRaises(PersistenceError):
                run_batch(correlation_id="test-rollback")

        # Ledger should still not exist (or be unchanged if it existed)
        self.assertFalse(os.path.exists(self.ledger_file))

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

    def test_observability_logs(self):
        """Verify that [OBSERVABILITY] logs are emitted correctly."""
        from io import StringIO
        with patch('sys.stdout', new=StringIO()) as fake_out:
            run_batch(correlation_id="obs-123")
            output = fake_out.getvalue()

            self.assertIn("[OBSERVABILITY] chain=dna_batch_parsing status=start correlation_id=obs-123", output)
            self.assertIn("[OBSERVABILITY] step=idempotency_check key=V100 hit=false", output)
            self.assertIn("[OBSERVABILITY] step=parse_dna key=V100 outcome=success", output)
            self.assertIn("[OBSERVABILITY] chain=dna_batch_parsing status=success correlation_id=obs-123 new_processed=1", output)

if __name__ == '__main__':
    unittest.main()

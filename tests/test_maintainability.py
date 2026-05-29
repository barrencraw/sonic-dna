import sys
from unittest.mock import MagicMock

# Mock dependencies
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
import io
from contextlib import redirect_stdout
from utils.dna_ui import main as run_batch, TerminalOutcome

class TestMaintainability(unittest.TestCase):
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
        with open(self.input_file, 'w') as f:
            f.write("V100\nINVALID\n")

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

    def test_naming_alignment_and_terminal_outcomes(self):
        """Verify dna_sequence key and TerminalOutcome values in outputs."""
        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        ledger_out = os.path.join(self.data_dir, 'processed_ledger.json')

        with open(json_out, 'r') as f:
            data = json.load(f)
            self.assertIn('dna_sequence', data[0])
            self.assertNotIn('dna', data[0])

        with open(ledger_out, 'r') as f:
            ledger = json.load(f)
            self.assertEqual(ledger['V100']['terminal_outcome'], TerminalOutcome.SUCCESS.value)
            self.assertEqual(ledger['INVALID']['terminal_outcome'], TerminalOutcome.PARSE_ERROR.value)

    def test_structured_logging(self):
        """Verify that structured logs are produced with required fields."""
        f = io.StringIO()
        with redirect_stdout(f):
            run_batch()

        output = f.getvalue()
        log_lines = [line for line in output.split('\n') if line.startswith('JSON_LOG: ')]
        self.assertTrue(len(log_lines) > 0)

        for line in log_lines:
            log_data = json.loads(line[len('JSON_LOG: '):])
            self.assertIn('correlation_id', log_data)
            self.assertIn('chain_name', log_data)
            self.assertIn('step', log_data)
            self.assertIn('outcome', log_data)
            self.assertIn('timestamp', log_data)
            self.assertIn('actor_id', log_data)

if __name__ == '__main__':
    unittest.main()

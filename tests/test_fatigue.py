import os
import sys
import json
import shutil
import tempfile
import unittest
import datetime as _dt
from unittest.mock import patch, MagicMock

# Mock C-extension dependencies before imports to enable standalone unittest execution
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()

mock_scipy = MagicMock()
sys.modules["scipy"] = mock_scipy
sys.modules["scipy.io"] = mock_scipy
sys.modules["scipy.io.wavfile"] = mock_scipy

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    LOCKOUT_THRESHOLD
)


class MockDatetime(_dt.datetime):
    fixed_now = _dt.datetime(2026, 3, 2, 12, 0, 0, tzinfo=_dt.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.fixed_now


class MockDatetimeModule:
    datetime = MockDatetime
    timezone = _dt.timezone


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Create a valid Volume rule (3-char prefix + 3 subvars of 3 digits = 12 chars total)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                    "fade": {"description": "fade", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_fatigue_idempotency(self):
        """Verify heat accumulation and outputs are applied exactly once per unique sequence (idempotency)."""
        dna_seq = "VOL089007507"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        # First run
        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], HEAT_PER_SEQUENCE)
        self.assertIn(dna_seq, ledger_data['ledger'])
        self.assertEqual(ledger_data['ledger'][dna_seq]['terminal_outcome'], 'success')

        with open(self.json_output, 'r', encoding='utf-8') as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 1)

        # Second run with same sequence (duplicate invocation)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna_seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data2 = json.load(f)

        # Core heat should NOT increase on deduplicated sequence
        self.assertEqual(ledger_data2['system_state']['core_heat'], HEAT_PER_SEQUENCE)
        with open(self.json_output, 'r', encoding='utf-8') as f:
            parsed2 = json.load(f)
        self.assertEqual(len(parsed2), 1, "Duplicate sequence must not add redundant output entries")

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_lockout_no_silent_drains(self):
        """Verify lockout triggers ThermalOverloadError, surfaces message keys, and prevents silent drains."""
        # Write 6 distinct valid 12-char sequences (5 * 2.0 = 10.0 heat units max allowed; 6th triggers lockout)
        sequences = [f"VOL08900750{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_CONSEQUENCE_APPLIED, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Verify state persistence on refusal: initial ledger preserved for output consistency, heat set to accumulated level
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)
        self.assertEqual(len(ledger_data['ledger']), 0, "Ledger must stay consistent with output files when run aborts mid-batch")

        # Test main.py process_once watcher behavior: input file should NOT be cleared on failure
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Check input file was NOT cleared (no silent drain)
        with open(self.input_file, 'r', encoding='utf-8') as f:
            retained_content = f.read().strip()
        self.assertTrue(len(retained_content) > 0, "Input file must not be cleared when processing is refused")


if __name__ == '__main__':
    unittest.main()

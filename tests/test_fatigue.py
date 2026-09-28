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
sys.modules["numpy"] = MagicMock()
mock_scipy = MagicMock()
sys.modules["scipy"] = mock_scipy
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    HEAT_LOCKOUT_THRESHOLD,
    load_ledger
)

class TestThermalFatigueSystem(unittest.TestCase):
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

        # Mock rule file for Volume ('V' prefix)
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

    def test_heat_accumulation_and_thermal_lockout(self):
        """
        Verify core heat accumulation (+2.0/seq) and ThermalOverloadError lockout at threshold (10.0).
        """
        # Write 6 sequences (6 * 2.0 = 12.0 heat, exceeding threshold 10.0)
        sequences = [f"V10{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        now = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

        class MockDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err_msg = str(cm.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_CONSEQUENCE_APPLIED, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Check that 4 sequences were processed before hitting threshold (4 * 2.0 = 8.0 heat)
        ledger, system_state = load_ledger(self.ledger_file)
        self.assertEqual(len(ledger), 4)
        self.assertEqual(system_state['core_heat'], 8.0)

    def test_thermal_dissipation(self):
        """
        Verify passive core heat dissipation (-0.5 units/sec).
        """
        sequences = [f"V10{i}" for i in range(4)] # Accumulates 8.0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        t0 = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

        class MockDatetime1(datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime', MockDatetime1):
            run_batch()

        ledger, system_state = load_ledger(self.ledger_file)
        self.assertEqual(system_state['core_heat'], 8.0)

        # 10 seconds later -> 8.0 - (10 * 0.5) = 3.0 core heat
        t1 = t0 + timedelta(seconds=10)

        class MockDatetime2(datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        # Now submit 3 more new sequences (+6.0 heat -> 3.0 + 6.0 = 9.0 heat < 10.0 threshold)
        new_sequences = [f"V20{i}" for i in range(3)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(new_sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime2):
            run_batch()

        ledger, system_state = load_ledger(self.ledger_file)
        self.assertEqual(len(ledger), 7)
        self.assertEqual(system_state['core_heat'], 9.0)

    def test_idempotency_no_heat_accumulation_and_no_silent_drains(self):
        """
        Verify that deduplicated sequences generate no core heat (applied exactly once)
        and thermal lockout does not silently drain input files in main.py.
        """
        sequences = ["V100", "V101"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        t0 = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

        class MockDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger, system_state = load_ledger(self.ledger_file)
        self.assertEqual(system_state['core_heat'], 4.0)

        # Re-run batch with same deduplicated sequences at same timestamp
        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger, system_state = load_ledger(self.ledger_file)
        self.assertEqual(system_state['core_heat'], 4.0, "Deduplicated sequences must NOT generate additional core heat")

        # Verify main.py process_once preserves toSequence.txt on ThermalOverloadError (no silent drain)
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Add 5 NEW sequences to push total past lockout threshold (4.0 existing heat + 5 * 2.0 = 14.0 >= 10.0)
        more_sequences = [f"V30{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(more_sequences) + "\n")

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('utils.dna_ui.datetime', MockDatetime):
                with self.assertRaises(SystemExit):
                    main.process_once()

        # Input file MUST NOT be cleared on failure / lockout
        with open(self.input_file, 'r') as f:
            remaining_content = f.read().strip().split('\n')
        self.assertGreater(len(remaining_content), 0, "Input file must not be cleared on ThermalOverloadError")

if __name__ == '__main__':
    unittest.main()

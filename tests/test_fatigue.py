import os
import sys
from unittest.mock import MagicMock

# Mock GUI dependencies if needed before any imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)

class MockDatetimeModule:
    class datetime:
        current_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return datetime.strptime(date_string, format_spec)

        @classmethod
        def fromisoformat(cls, date_string):
            return datetime.fromisoformat(date_string)

    timezone = timezone

class TestThermalFatigue(unittest.TestCase):
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

        # Mock rule file for Volume ('VOL')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset mock time
        MockDatetimeModule.datetime.current_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_idempotency(self):
        """Verify heat accumulates (+2.0/seq) once and duplicate inputs hit dedupe (0 heat added)."""
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)
        self.assertIn('VOL100', ledger_data['ledger'])

        # Second run with exact same sequence (dedupe hit)
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # Heat should remain 2.0 (no extra heat added for duplicate)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    def test_thermal_lockout_and_message_keys(self):
        """Verify threshold lockout raises ThermalOverloadError with precise UI message keys."""
        # 5 sequences = 5 * 2.0 = 10.0 core heat -> reaches threshold
        sequences = ["VOL001\n", "VOL002\n", "VOL003\n", "VOL004\n", "VOL005\n"]
        with open(self.input_file, 'w') as f:
            f.writelines(sequences)

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, MSG_CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, MSG_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, MSG_NEXT_ACTION_HINT)
        self.assertIn(MSG_REFUSAL_REASON, str(err))
        self.assertIn(MSG_NEXT_ACTION_HINT, str(err))

    def test_deterministic_dissipation_over_time(self):
        """Verify core heat dissipates at 0.5 units/sec over elapsed time."""
        # Process 4 sequences = 8.0 heat
        sequences = ["VOL010\n", "VOL020\n", "VOL030\n", "VOL040\n"]
        with open(self.input_file, 'w') as f:
            f.writelines(sequences)

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds -> dissipation = 10 * 0.5 = 5.0 heat -> remaining = 3.0
        MockDatetimeModule.datetime.current_time += timedelta(seconds=10)

        # Now process 1 new sequence (+2.0 heat) -> total heat should be 3.0 + 2.0 = 5.0
        with open(self.input_file, 'w') as f:
            f.write("VOL050\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 5.0)

    def test_no_silent_drains_on_refusal(self):
        """Verify that on ThermalOverloadError, watcher/main.py preserves input file."""
        sequences = ["VOL101\n", "VOL102\n", "VOL103\n", "VOL104\n", "VOL105\n"]
        with open(self.input_file, 'w') as f:
            f.writelines(sequences)

        if 'main' in sys.modules:
            del sys.modules['main']
        import main
        main.__file__ = os.path.join(self.test_dir, 'main.py')

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):
                    main.process_once()

                mock_clear.assert_not_called()

        # Input file must NOT be cleared or drained
        with open(self.input_file, 'r') as f:
            content = f.read()
            self.assertTrue(len(content.strip()) > 0)

if __name__ == '__main__':
    unittest.main()

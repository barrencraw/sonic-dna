import sys
from unittest.mock import MagicMock

# Mock dependencies before imports
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
import datetime as real_datetime
from unittest.mock import patch
import utils.dna_ui
from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    DNAStatus,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)

class MockDatetime:
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def set_time(cls, new_dt):
        cls.current_time = new_dt

    @classmethod
    def advance(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.datetime.strptime(date_string, format_string)

    timezone = real_datetime.timezone

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

        # Copy rules
        real_rules_dir = os.path.join(os.getcwd(), 'rules')
        if os.path.exists(real_rules_dir):
            for fname in os.listdir(real_rules_dir):
                if fname.endswith('.json'):
                    shutil.copy(os.path.join(real_rules_dir, fname), os.path.join(self.rules_dir, fname))

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        MockDatetime.set_time(real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        """Verify heat accumulates per sequence and triggers ThermalOverloadError at/above threshold."""
        # 5 valid sequences = 10.0 heat units
        seqs = [
            "VOL08900750711",
            "VOL08900750712",
            "VOL08900750713",
            "VOL08900750714",
            "VOL08900750715"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # 6th sequence exceeds maximum heat -> refusal
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750716\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_CONSEQUENCE_APPLIED, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

    def test_time_based_heat_decay(self):
        """Verify core heat cools down over time at 0.5 units/sec."""
        seqs = [
            "VOL08900750711",
            "VOL08900750712",
            "VOL08900750713",
            "VOL08900750714",
            "VOL08900750715"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        # Advance time by 10 seconds => cools down by 5.0 heat units (10.0 -> 5.0)
        MockDatetime.advance(10)

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750716\nVOL08900750717\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # 5.0 heat + 2*2.0 = 9.0 heat
        self.assertEqual(ledger_data['system_state']['core_heat'], 9.0)

    def test_idempotency_does_not_accumulate_heat(self):
        """Deduplicated sequence hits do not add heat."""
        seq = "VOL08900750711"
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Submit same sequence again
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0, "Deduplicated sequence must not add heat")

    def test_no_silent_drains_on_overload(self):
        """Watcher/main.py must not clear input file when ThermalOverloadError occurs."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Fill heat to 10.0
        seqs = [
            "VOL08900750711",
            "VOL08900750712",
            "VOL08900750713",
            "VOL08900750714",
            "VOL08900750715"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        overload_seq = "VOL08900750716"
        with open(self.input_file, 'w') as f:
            f.write(overload_seq + "\n")

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('utils.dna_ui.datetime', MockDatetime):
                with self.assertRaises(SystemExit):
                    main.process_once()

        # Input file must NOT have been cleared
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), overload_seq)

if __name__ == '__main__':
    unittest.main()

import os
import sys
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime
from unittest.mock import patch, MagicMock

# Mock native dependencies before imports if needed
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6

from utils.dna_ui import (
    main as run_batch,
    load_ledger,
    save_ledger,
    ThermalOverloadError,
    CONSEQUENCE_APPLIED,
    REFUSAL_REASON,
    NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    LOCKOUT_THRESHOLD,
    DISSIPATION_RATE
)

class MockDatetime:
    timezone = real_datetime.timezone
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def set_time(cls, dt):
        cls.current_time = dt

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return MockDatetime.current_time.astimezone(tz)
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_str):
            return real_datetime.datetime.strptime(date_string, format_str)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        MockDatetime.set_time(real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

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
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "pan level", "min": 0, "max": 999, "pad": 3},
                    "mute": {"description": "mute flag", "min": 0, "max": 999, "pad": 3},
                    "solo": {"description": "solo flag", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_thermal_lockout(self):
        """Verify that parsing sequences accumulates heat (+2.0) and lockout triggers at >=10.0 heat."""
        # Write 6 valid unique DNA sequences
        sequences = [f"VOL00{i}00000012" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        # 5 sequences * 2.0 heat = 10.0 heat. 6th sequence will exceed limit -> ThermalOverloadError
        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertIn(REFUSAL_REASON, str(cm.exception))

        # Check persisted core_heat in ledger
        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)
        # On thermal overload, uncommitted batch items are not saved to ledger to keep state consistent with output files
        self.assertEqual(len(ledger_data['ledger']), 0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_passive_thermal_dissipation(self):
        """Verify that heat dissipates over time at 0.5 units/second."""
        # 1. Heat up system to 10.0 heat (5 sequences)
        sequences = [f"VOL00{i}00000012" for i in range(1, 6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # 2. Attempt another sequence immediately -> Refused due to lockout
        next_seq = "VOL00600000012"
        with open(self.input_file, 'w') as f:
            f.write(next_seq + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # 3. Advance time by 10 seconds -> dissipation = 10s * 0.5 = 5.0 heat reduction -> core_heat = 5.0
        MockDatetime.advance_seconds(10)

        ledger_data_cooled = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data_cooled['system_state']['core_heat'], 5.0)

        # 4. Now processing new sequence succeeds!
        run_batch()
        ledger_data_final = load_ledger(self.ledger_file)
        # Heat was 5.0 + 2.0 = 7.0
        self.assertEqual(ledger_data_final['system_state']['core_heat'], 7.0)
        self.assertIn(next_seq, ledger_data_final['ledger'])

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_does_not_accumulate_heat(self):
        """Verify duplicate sequence submissions hit deduplication and generate no additional heat."""
        seq = "VOL00100000012"
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        run_batch()
        ledger_1 = load_ledger(self.ledger_file)
        self.assertEqual(ledger_1['system_state']['core_heat'], 2.0)

        # Submit same sequence again
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        run_batch()
        ledger_2 = load_ledger(self.ledger_file)
        # Heat remains 2.0 because deduplication skipped re-parsing
        self.assertEqual(ledger_2['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_main_preserves_input_on_thermal_overload(self):
        """Verify main.py / process_once preserves toSequence.txt when ThermalOverloadError is raised."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        sandbox_main_file = os.path.join(self.test_dir, 'main.py')

        # Fill input file with 6 sequences
        sequences = [f"VOL00{i}00000012" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('main.__file__', sandbox_main_file):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file MUST NOT have been cleared (no silent drains!)
        with open(self.input_file, 'r') as f:
            remaining_content = f.read().strip().splitlines()

        self.assertEqual(len(remaining_content), 6)

if __name__ == '__main__':
    unittest.main()

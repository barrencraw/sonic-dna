import sys
import os
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime
from unittest.mock import patch, MagicMock

# Mock C-extension dependencies if missing
if "numpy" not in sys.modules:
    try:
        import numpy
    except ImportError:
        sys.modules["numpy"] = MagicMock()
if "scipy" not in sys.modules:
    try:
        import scipy
    except ImportError:
        mock_scipy = MagicMock()
        sys.modules["scipy"] = mock_scipy
        sys.modules["scipy.io"] = mock_scipy.io
        sys.modules["scipy.io.wavfile"] = mock_scipy.io.wavfile

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    load_ledger,
    save_ledger,
    UI_CONSEQUENCE_APPLIED,
    UI_REFUSAL_REASON,
    UI_NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    LOCKOUT_THRESHOLD,
    COOLING_RATE_PER_SEC
)


class MockDatetimeModule:
    timezone = real_datetime.timezone

    class datetime:
        current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def advance_seconds(cls, seconds):
            cls.current_time += real_datetime.timedelta(seconds=seconds)


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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock Volume rule
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
        MockDatetimeModule.datetime.current_time = real_datetime.datetime(
            2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc
        )

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_thermal_lockout(self):
        """
        Verify that each parsed sequence accumulates 2.0 heat units,
        and exceeding 10.0 heat units raises ThermalOverloadError.
        """
        # Create 6 distinct valid DNA sequences (6 * 2.0 = 12.0 heat units > 10.0 threshold)
        dna_sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

            err_msg = str(cm.exception)
            self.assertIn(UI_REFUSAL_REASON, err_msg)
            self.assertIn(UI_NEXT_ACTION_HINT, err_msg)

            # Check ledger state: original ledger preserved on overload, system state updated with core heat
            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(len(ledger), 0)
            self.assertEqual(system_state['core_heat'], 10.0)

    def test_idempotency_does_not_accumulate_heat(self):
        """
        Verify that deduplicated (already processed) sequences do not add heat.
        """
        dna = "VOL00100000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch() # 1st run: heat = 2.0

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(system_state['core_heat'], 2.0)

            # Run again with same DNA sequence
            run_batch() # 2nd run: deduplicated, heat remains 2.0

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(system_state['core_heat'], 2.0)

    def test_cooling_dissipation_over_time(self):
        """
        Verify that heat dissipates over time at 0.5 units/sec.
        """
        # Process 5 sequences -> 10.0 heat
        dna_sequences = [f"VOL{i:03d}00000000" for i in range(1, 6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(system_state['core_heat'], 10.0)

            # Advance time by 10 seconds (10s * 0.5 = 5.0 heat dissipated)
            MockDatetimeModule.datetime.advance_seconds(10)

            # Process 1 new sequence (requires +2.0 heat; current heat = 10.0 - 5.0 = 5.0; 5.0 + 2.0 = 7.0 <= 10.0)
            new_dna = "VOL09900000000"
            with open(self.input_file, 'w') as f:
                f.write(f"{new_dna}\n")

            run_batch()

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(system_state['core_heat'], 7.0)
            self.assertIn(new_dna, ledger)

    def test_no_silent_drains_on_overload(self):
        """
        Verify that when ThermalOverloadError is raised, process_once in main.py
        exits with failure and does NOT clear toSequence.txt.
        """
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        fake_main_file = os.path.join(self.test_dir, 'main.py')

        # 6 sequences -> triggers overload on 6th
        dna_sequences = [f"VOL{i:03d}00000000" for i in range(1, 7)]
        input_text = "\n".join(dna_sequences) + "\n"
        with open(self.input_file, 'w') as f:
            f.write(input_text)

        with patch.object(main, '__file__', fake_main_file):
            with patch('utils.dna_ui.datetime', MockDatetimeModule):
                with self.assertRaises(SystemExit) as cm:
                    main.process_once()

                self.assertEqual(cm.exception.code, 1)

        # Confirm input file was NOT cleared (no silent drain)
        with open(self.input_file, 'r') as f:
            content = f.read()
            self.assertEqual(content, input_text)


if __name__ == '__main__':
    unittest.main()

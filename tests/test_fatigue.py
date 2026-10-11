import os
import sys
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime
from unittest.mock import patch, MagicMock

# Mock GUI / C-extensions if needed
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

try:
    import numpy
except ImportError:
    sys.modules["numpy"] = MagicMock()

from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger, save_ledger

class MockDatetimeModule:
    timezone = real_datetime.timezone

    class datetime:
        current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return real_datetime.datetime.strptime(date_string, format_spec)

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
        rule_content = {
            "variable": "Volume",
            "prefix": "VOL",
            "subvars": {
                "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
            }
        }
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump(rule_content, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        # 5 sequences -> 5 * 2.0 = 10.0 heat units.
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Check stored heat
        ledger = load_ledger(self.ledger_file)
        self.assertEqual(ledger['system_state']['core_heat'], 10.0)

        # 6th sequence should trigger ThermalOverloadError
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750719\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_heat_dissipation_over_time(self):
        mock_dt = MockDatetimeModule()
        mock_dt.datetime.current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        with patch('utils.dna_ui.datetime', mock_dt):
            # Accumulate 10.0 heat
            sequences = [f"VOL0890075071{i}" for i in range(5)]
            with open(self.input_file, 'w') as f:
                f.write("\n".join(sequences) + "\n")

            run_batch()

            ledger = load_ledger(self.ledger_file)
            self.assertEqual(ledger['system_state']['core_heat'], 10.0)

            # Advance simulated time by 10 seconds -> dissipation = 10 * 0.5 = 5.0 -> core_heat = 5.0
            mock_dt.datetime.current_time += real_datetime.timedelta(seconds=10)

            # Submit new sequence -> 5.0 + 2.0 = 7.0 heat <= 10.0 threshold
            with open(self.input_file, 'w') as f:
                f.write("VOL08900750799\n")

            run_batch()

            updated_ledger = load_ledger(self.ledger_file)
            self.assertEqual(updated_ledger['system_state']['core_heat'], 7.0)

    def test_idempotency_no_heat_addition(self):
        seq = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{seq}\n")

        run_batch()
        ledger1 = load_ledger(self.ledger_file)
        self.assertEqual(ledger1['system_state']['core_heat'], 2.0)

        # Re-submitting same deduplicated sequence
        with open(self.input_file, 'w') as f:
            f.write(f"{seq}\n")

        run_batch()
        ledger2 = load_ledger(self.ledger_file)
        # Heat should NOT increase for deduplicated sequence
        self.assertEqual(ledger2['system_state']['core_heat'], 2.0)

    def test_no_silent_drains_watcher_preserves_input_on_overload(self):
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Fill heat to lockout threshold (10.0)
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch()

        # Place new sequence in input file
        overload_seq = "VOL08900750799\n"
        with open(self.input_file, 'w') as f:
            f.write(overload_seq)

        main_file = os.path.join(self.test_dir, 'main.py')
        with patch.object(main, '__file__', main_file):
            # Run process_once which catches ThermalOverloadError
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file MUST NOT be cleared (no silent drains)
        with open(self.input_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, overload_seq)

if __name__ == '__main__':
    unittest.main()

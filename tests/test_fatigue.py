import sys
from unittest.mock import MagicMock

# Mock non-essential GUI and audio/math dependencies for headless tests
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
mock_scipy = MagicMock()
sys.modules["scipy"] = mock_scipy
sys.modules["scipy.io"] = mock_scipy
sys.modules["scipy.io.wavfile"] = mock_scipy

import os
import json
import shutil
import unittest
import tempfile
import datetime as real_datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, DNAProcessingError, load_ledger

class MockDatetime:
    timezone = real_datetime.timezone

    class datetime:
        current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def set_time(cls, dt):
            cls.current_time = dt

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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule file for Volume ('VOL')
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Reset mock datetime
        MockDatetime.datetime.current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_applied_once(self):
        """Verify that newly processed DNA sequence adds 2.0 heat units."""
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL001\n")

        run_batch()

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)
        self.assertIn("VOL001", ledger_data['ledger'])

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_extra_heat(self):
        """Verify that duplicate/already ledgered DNA sequences generate 0 extra heat."""
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL001\n")

        run_batch() # 1st run -> 2.0 heat

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL001\n")

        run_batch() # 2nd run -> deduplicated, heat remains 2.0

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_time_decay(self):
        """Verify core heat dissipates at 0.5 units/sec over time."""
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL001\nVOL002\n")

        run_batch() # 2 sequences -> 4.0 heat

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 4.0)

        # Advance simulated time by 4 seconds (4.0 - 4.0*0.5 = 2.0 core heat remaining)
        MockDatetime.datetime.advance_seconds(4)

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL003\n")

        run_batch() # +2.0 heat => 2.0 (after dissipation) + 2.0 = 4.0

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_refusal_and_messages(self):
        """Verify that pushing heat above 10.0 raises ThermalOverloadError with UI message keys."""
        # Write 6 sequences (6 * 2.0 = 12.0 heat, which exceeds max limit 10.0)
        sequences = [f"VOL00{i}" for i in range(1, 7)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains(self):
        """Verify that on ThermalOverloadError, input file content is preserved."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        sequences = [f"VOL00{i}" for i in range(1, 7)]
        input_text = "\n".join(sequences) + "\n"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(input_text)

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with patch.object(main, 'run_batch', side_effect=run_batch):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()

                    mock_clear.assert_not_called()

        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), input_text)


if __name__ == '__main__':
    unittest.main()

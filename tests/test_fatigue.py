import sys
from unittest.mock import MagicMock, patch

# Mock PySide6 and heavy audio/ml dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import os
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime

from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger, save_ledger

class MockDatetimeModule:
    timezone = real_datetime.timezone
    _current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetimeModule._current_time

        @classmethod
        def strptime(cls, date_string, format_str):
            return real_datetime.datetime.strptime(date_string, format_str)

        @classmethod
        def fromisoformat(cls, date_string):
            return real_datetime.datetime.fromisoformat(date_string)

    @classmethod
    def set_time(cls, new_dt):
        cls._current_time = new_dt

    @classmethod
    def advance_seconds(cls, seconds):
        cls._current_time = cls._current_time + real_datetime.timedelta(seconds=seconds)


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

        # Create valid Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "master_fader_level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "peak_headroom": {"description": "headroom", "min": 0, "max": 999, "pad": 3},
                    "dynamic_range": {"description": "dynamic range", "min": 0, "max": 999, "pad": 3},
                    "stereo_pan": {"sign": "+", "min": 0, "max": 99, "pad": 2, "description": "stereo pan"}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        MockDatetimeModule.set_time(real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_lockout(self):
        """Verify heat accumulates +2.0 per sequence and triggers ThermalOverloadError at threshold 10.0."""
        # 5 valid distinct sequences with signed stereo pan
        sequences = [f"VOL089007507+1{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Check core heat after 5 sequences
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        system_state = data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), 10.0)

        # 6th sequence attempt should be refused due to lockout
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL089007507+15\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err_msg = str(ctx.exception)
        self.assertIn("Heat Accumulation", err_msg)
        self.assertIn("Thermal Lockout", err_msg)
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", err_msg)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_dissipation_over_time(self):
        """Verify core heat cools down at 0.5 units per second."""
        sequences = [f"VOL089007507+1{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Advance simulated time by 10 seconds -> 10 * 0.5 = 5.0 heat decayed (10.0 -> 5.0)
        MockDatetimeModule.advance_seconds(10)

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL089007507+15\n")

        # Now parsing should succeed
        run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        system_state = data.get('system_state', {})
        # 5.0 remaining + 2.0 new sequence = 7.0
        self.assertAlmostEqual(system_state.get('core_heat'), 7.0, places=2)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_no_extra_heat(self):
        """Verify re-parsing deduplicated sequences does not add extra heat."""
        seq = "VOL089007507+12"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + "\n")

        run_batch() # 1 sequence -> 2.0 heat

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # Re-run same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + "\n")

        run_batch() # Deduplicated -> 0 heat added

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains_input_file_preserved(self):
        """Verify that when thermal overload occurs, input file in main.py watcher is NOT cleared."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Fill core heat to 10.0
        sequences = [f"VOL089007507+1{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Place new sequence in input file
        blocked_seq = "VOL089007507+19\n"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(blocked_seq)

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file should still contain the blocked sequence (no silent drain)
        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), blocked_seq.strip())

if __name__ == '__main__':
    unittest.main()

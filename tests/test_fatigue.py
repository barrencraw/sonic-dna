import sys
from unittest.mock import MagicMock

sys.modules.setdefault("PySide6", MagicMock())
sys.modules.setdefault("PySide6.QtWidgets", MagicMock())
sys.modules.setdefault("PySide6.QtCore", MagicMock())
sys.modules.setdefault("PySide6.QtGui", MagicMock())

import unittest
import os
import shutil
import tempfile
import json
import datetime as real_datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError

class MockDatetime(real_datetime.datetime):
    current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def advance_seconds(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)

class MockDatetimeModule:
    datetime = MockDatetime
    timezone = real_datetime.timezone
    timedelta = real_datetime.timedelta

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.old_cwd = os.getcwd()
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        actual_rules = os.path.join(self.old_cwd, 'rules')
        if os.path.exists(actual_rules):
            shutil.copytree(actual_rules, self.rules_dir, dirs_exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        os.chdir(self.test_dir)
        MockDatetime.current_time = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_lockout(self):
        # 5 unique sequences = 5 * 2.0 = 10.0 heat -> lockout on 5th sequence
        sequences = [f"VOL089007507{i:02d}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
            system_state = ledger_data.get('system_state', {})
            self.assertGreaterEqual(system_state.get('core_heat', 0.0), 10.0)

    def test_thermal_dissipation_over_time(self):
        # Add 8.0 heat (4 sequences)
        sequences = [f"VOL089007507{i:02d}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        # Advance simulated time by 10 seconds -> dissipation of 10 * 0.5 = 5.0 heat units
        MockDatetime.advance_seconds(10)

        new_sequences = [f"VOL089007507{i:02d}" for i in range(4, 7)] # +6.0 heat -> core_heat = (8.0-5.0) + 6.0 = 9.0 < 10.0
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(new_sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
            system_state = ledger_data.get('system_state', {})
            self.assertAlmostEqual(system_state.get('core_heat', 0.0), 9.0)

if __name__ == '__main__':
    unittest.main()

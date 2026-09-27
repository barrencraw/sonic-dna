import os
import sys
import json
import shutil
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Mock native C-extension modules before any imports
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import utils.dna_ui
from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, HEAT_PER_SEQUENCE, LOCKOUT_THRESHOLD


class FakeDatetime(datetime):
    current_time = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_spec):
        return datetime.strptime(date_string, format_spec)

    @classmethod
    def fromisoformat(cls, date_string):
        return datetime.fromisoformat(date_string)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Reset fake time
        FakeDatetime.current_time = datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc)

        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': '2026-03-02T12:00:00Z'}}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', FakeDatetime)
    def test_heat_accumulation_and_lockout_threshold(self):
        # 5 valid sequences -> 5 * 2.0 = 10.0 heat (at lockout limit)
        sequences = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Attempt 6th sequence without cooling down -> raises ThermalOverloadError
        next_seq = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(next_seq + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', FakeDatetime)
    def test_time_based_dissipation(self):
        # Fill heat to 10.0
        sequences = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch()

        # Advance time by 10 seconds -> 10s * 0.5 heat/sec = 5.0 cooling -> core heat becomes 5.0
        FakeDatetime.current_time += timedelta(seconds=10)

        new_seq = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(new_seq + "\n")

        # Run batch again -> core heat becomes 5.0 + 2.0 = 7.0
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 7.0)

    @patch('utils.dna_ui.datetime', FakeDatetime)
    def test_idempotency_no_unnecessary_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Re-submitting same DNA sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        # Heat should NOT increase on deduplicated input
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', FakeDatetime)
    def test_no_silent_drains_input_file_retained_on_lockout(self):
        # Fill heat to limit
        sequences = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch()

        # Place new sequence in input_file
        refused_seq = "VOL08900750799"
        with open(self.input_file, 'w') as f:
            f.write(refused_seq + "\n")

        # Simulate main.py process_once
        if 'main' in sys.modules:
            del sys.modules['main']
        import main
        main.__file__ = os.path.join(self.project_root, 'main.py')

        with self.assertRaises(SystemExit):
            main.process_once()

        # Input file MUST still contain refused_seq (no silent drains)
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, refused_seq)


if __name__ == '__main__':
    unittest.main()

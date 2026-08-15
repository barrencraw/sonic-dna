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
import datetime
import io
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetimeModule:
    timezone = datetime.timezone

    class datetime(datetime.datetime):
        _current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def strptime(cls, date_string, format):
            return datetime.datetime.strptime(date_string, format)

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
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        fixed_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetimeModule.datetime._current_time = fixed_time

        dnas = [f"VOL00{i}00{i}00{i}00" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger, sys_state = load_ledger(self.ledger_path)
        self.assertEqual(sys_state["core_heat"], 10.0)

        # Run 2: Try 6th sequence immediately at same fixed time -> Should trigger ThermalOverloadError
        new_dna = "VOL00900900900"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        self.assertIn("indifferent to your deadlines", str(ctx.exception))

        ledger, sys_state = load_ledger(self.ledger_path)
        self.assertIn(new_dna, ledger)
        self.assertEqual(ledger[new_dna]["terminal_outcome"], "refused")
        self.assertEqual(
            ledger[new_dna]["feedback"]["next_action_hint"],
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

    def test_heat_dissipation_over_time(self):
        fixed_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetimeModule.datetime._current_time = fixed_time

        dnas = [f"VOL00{i}00{i}00{i}00" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger, sys_state = load_ledger(self.ledger_path)
        self.assertEqual(sys_state["core_heat"], 10.0)

        # Simulate 10 seconds passing (dissipates 10.0 * 0.5 = 5.0 heat -> core_heat = 5.0)
        MockDatetimeModule.datetime._current_time = fixed_time + datetime.timedelta(seconds=10)

        new_dna = "VOL00900900900"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        ledger, sys_state = load_ledger(self.ledger_path)
        # Heat was 10.0 - 5.0 (decay) + 2.0 (new_dna) = 7.0
        self.assertEqual(sys_state["core_heat"], 7.0)

    def test_structured_telemetry_logging(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            run_batch(correlation_id="test-corr-id-1234")
            output = fake_out.getvalue()

        json_logs = []
        for line in output.splitlines():
            if line.startswith("JSON_LOG: "):
                json_logs.append(json.loads(line[len("JSON_LOG: "):]))

        self.assertGreater(len(json_logs), 0)
        start_log = json_logs[0]
        self.assertEqual(start_log["correlation_id"], "test-corr-id-1234")
        self.assertEqual(start_log["chain_name"], "dna_batch_parser")
        self.assertIn("timestamp", start_log)
        self.assertIn("outcome", start_log)

if __name__ == '__main__':
    unittest.main()

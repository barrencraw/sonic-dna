import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError, load_ledger

class MockDatetimeModule:
    timezone = datetime.timezone

    class datetime:
        _current_time = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def set_time(cls, dt):
            cls._current_time = dt

        @classmethod
        def advance_seconds(cls, seconds):
            cls._current_time += datetime.timedelta(seconds=seconds)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def strptime(cls, date_string, format_str):
            return datetime.datetime.strptime(date_string, format_str)


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

        MockDatetimeModule.datetime.set_time(
            datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        )

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_heat_accumulation_and_cooling(self):
        # 1. Process 3 valid sequences (+2.0 heat each = 6.0U)
        dnas = ["VOL08900750712", "VOL00000000000", "VOL01111111111"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        self.assertEqual(state["system_state"]["core_heat"], 6.0)

        # 2. Advance time by 4 seconds (cooling rate = 0.5U/s => -2.0U cooling => 4.0U)
        MockDatetimeModule.datetime.advance_seconds(4)

        # Process 1 more sequence (+2.0 heat => 6.0U)
        with open(self.input_file, 'w') as f:
            f.write("VOL02222222222\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        self.assertEqual(state["system_state"]["core_heat"], 6.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_lockout_refusal(self):
        # 5 sequences = 5 * 2.0 = 10.0U, reaching MAX_HEAT_THRESHOLD (10.0)
        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL01111111111",
            "VOL02222222222",
            "VOL03333333333"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(
            err.next_action_hint,
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

        # Verify heat level was saved prior to exception
        state = load_ledger(self.ledger_path)
        self.assertEqual(state["system_state"]["core_heat"], 8.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_no_heat_gain_on_dedupe_hits(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        state1 = load_ledger(self.ledger_path)
        self.assertEqual(state1["system_state"]["core_heat"], 2.0)

        # Re-run same sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        state2 = load_ledger(self.ledger_path)
        # Deduplication hit: core_heat does not increase
        self.assertEqual(state2["system_state"]["core_heat"], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains_on_refusal(self):
        # Input file contains 5 sequences which will trigger lockout
        dnas = [f"VOL0890075071{i}" for i in range(5)]
        input_content = "\n".join(dnas) + "\n"
        with open(self.input_file, 'w') as f:
            f.write(input_content)

        try:
            run_batch()
        except ThermalOverloadError:
            pass

        # Verify input file was NOT drained / deleted on refusal
        with open(self.input_file, 'r') as f:
            content = f.read()

        self.assertEqual(content, input_content, "Input file must not be silently drained on refusal")

if __name__ == '__main__':
    unittest.main()

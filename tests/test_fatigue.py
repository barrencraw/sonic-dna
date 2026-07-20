import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError

# --- Mock Datetime Class Structure ---
class MockDatetime:
    timezone = datetime.timezone
    _current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def set_time(cls, dt):
        cls._current_time = dt

    @classmethod
    def advance_time(cls, seconds):
        cls._current_time += datetime.timedelta(seconds=seconds)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._current_time

        @classmethod
        def fromisoformat(cls, s):
            return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty structured ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 0.0,
                "last_processed_time": "2026-03-02T12:00:00Z",
                "ledger": {}
            }, f)

        # Reset Mock Time
        MockDatetime.set_time(datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc))

        # Start standard datetime patch
        self.patcher = patch('utils.dna_ui.datetime', MockDatetime)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 2 sequences -> Heat should accumulate to 40.0
        dna_list = ["VOL08900750712", "VOL00000000000"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        # assertions using non-strict comparison as recommended
        self.assertAlmostEqual(data['system_heat'], 40.0, places=2)
        self.assertEqual(len(data['ledger']), 2)

    def test_heat_dissipation(self):
        # 1. Accumulate heat
        dna_list = ["VOL08900750712", "VOL00000000000"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")
        run_batch()

        # 2. Advance time by 10 seconds -> 10 * 2.0 = 20.0 cooling
        MockDatetime.advance_time(10)

        # 3. Process another sequence
        dna_list_2 = ["VOL05005005005"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list_2) + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        # Initial 40.0 - 20.0 cooled + 20.0 new seq = 40.0
        self.assertAlmostEqual(data['system_heat'], 40.0, places=2)

    def test_thermal_lockout_and_refused(self):
        # 6 sequences -> 5 * 20 = 100.0 (MAX_HEAT). 6th should exceed and raise ThermalOverloadError
        dna_list = [
            "VOL08100750712",
            "VOL08200750712",
            "VOL08300750712",
            "VOL08400750712",
            "VOL08500750712",
            "VOL08600750712"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertAlmostEqual(data['system_heat'], 100.0, places=2)
        self.assertEqual(data['ledger'][dna_list[5]]['terminal_outcome'], 'refused')
        self.assertEqual(data['ledger'][dna_list[0]]['terminal_outcome'], 'success')

    def test_idle_cooling_persistence(self):
        # Accumulate heat
        dna_list = ["VOL08900750712"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")
        run_batch()

        # Idle cooling (empty input)
        with open(self.input_file, 'w') as f:
            f.write("")

        MockDatetime.advance_time(5) # 5 * 2.0 = 10.0 cooling
        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        # 20.0 - 10.0 = 10.0
        self.assertAlmostEqual(data['system_heat'], 10.0, places=2)


if __name__ == '__main__':
    unittest.main()

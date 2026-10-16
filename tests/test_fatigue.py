import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    LOCKOUT_THRESHOLD,
    COOLING_RATE_PER_SEC
)

class MockDatetime:
    timezone = datetime.timezone
    current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return datetime.datetime.strptime(date_string, format_spec)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_idempotency(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 4.0)

        # Second batch: re-submitting same sequences (deduplication)
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 4.0, "Duplicate sequence should not add core heat")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_no_silent_drains(self):
        sequences = [f"VOL000000000{i}0" for i in range(6)]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertIn(MSG_REFUSAL_REASON, str(cm.exception))
        self.assertIn(MSG_NEXT_ACTION_HINT, str(cm.exception))

        with open(self.input_file, 'r') as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 6, "Input file must not be silently drained on thermal lockout")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        dna = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # Advance mock time by 4 seconds (cooling rate = 0.5/sec -> 4s * 0.5 = -2.0 heat -> 0.0 heat)
        MockDatetime.current_time += datetime.timedelta(seconds=4)

        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 2.0)


if __name__ == '__main__':
    unittest.main()

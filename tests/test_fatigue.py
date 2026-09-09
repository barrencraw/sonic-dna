import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch

import utils.dna_ui as dna_ui
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    CONSEQUENCE_KEY,
    REFUSAL_REASON_KEY,
    NEXT_ACTION_HINT_KEY,
    HEAT_PER_SEQUENCE,
    MAX_HEAT_THRESHOLD,
    COOLING_RATE_PER_SEC
)


class MockDatetime:
    timezone = datetime.timezone
    current_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

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

        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_state(self):
        # VOL08900750712 is valid Volume DNA sequence
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertEqual(ledger_data['system_state']['core_heat'], HEAT_PER_SEQUENCE)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_refusal_and_message_keys(self):
        # 6 sequences * 2.0 heat = 12.0 heat > 10.0 threshold
        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004",
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(REFUSAL_REASON_KEY, err_msg)
        self.assertIn(NEXT_ACTION_HINT_KEY, err_msg)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_does_not_accumulate_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        initial_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(initial_heat, 2.0)

        # Re-run same sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        # Deduplicated hit should not increase heat
        self.assertLessEqual(ledger_data['system_state']['core_heat'], initial_heat)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        # 1. Generate 8.0 heat (4 sequences)
        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds => 10s * 0.5 heat/s = 5.0 heat dissipated
        # Core heat should decay to 3.0
        MockDatetime.current_time += datetime.timedelta(seconds=10)

        # Process 1 new sequence (adds 2.0 heat -> total 5.0)
        new_dna = "VOL00000000003"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 5.0, places=2)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_thermal_overload(self):
        import main

        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004",
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(SystemExit):
            main.process_once()

        # Input file MUST NOT be cleared on failure/refusal
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertTrue(len(content) > 0)
        self.assertIn("VOL08900750712", content)


if __name__ == '__main__':
    unittest.main()

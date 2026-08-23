import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    HEAT_PER_PARSE,
    HEAT_LOCKOUT_THRESHOLD,
    COOLING_RATE_PER_SEC,
    UI_MESSAGES
)

_real_datetime = datetime.datetime

class MockDatetimeModule:
    def __init__(self, initial_dt):
        self.current_dt = initial_dt
        self.timezone = datetime.timezone
        self.timedelta = datetime.timedelta

    @property
    def datetime(self):
        current_dt = self.current_dt
        class MockInnerDatetime:
            @staticmethod
            def now(tz=None):
                return current_dt

            @staticmethod
            def strptime(date_string, format):
                return _real_datetime.strptime(date_string, format)

        return MockInnerDatetime

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

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        self.start_dt = _real_datetime(2026, 8, 23, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.mock_mod = MockDatetimeModule(self.start_dt)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_idempotency_applied_once(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with patch('utils.dna_ui.datetime', self.mock_mod):
            # 1. Process initial sequence -> heat should increase by +2.0
            with open(self.input_file, 'w') as f:
                f.write(dna1 + "\n")

            run_batch()

            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)

            self.assertEqual(ledger['system_state']['core_heat'], 2.0)
            self.assertIn(dna1, ledger)

            # 2. Re-process SAME sequence immediately -> idempotency hit, heat must NOT increase (applied exactly once)
            with open(self.input_file, 'w') as f:
                f.write(dna1 + "\n")

            run_batch()

            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)

            self.assertEqual(ledger['system_state']['core_heat'], 2.0, "Idempotent execution must not accumulate heat")

            # 3. Process new sequence immediately -> heat should accumulate further by +2.0 to 4.0
            with open(self.input_file, 'w') as f:
                f.write(dna2 + "\n")

            run_batch()

            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)

            self.assertEqual(ledger['system_state']['core_heat'], 4.0)
            self.assertIn(dna2, ledger)

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        initial_ledger = {
            "VOL00000000001": {"terminal_outcome": "success", "timestamp": "2026-08-23 12:00:00"},
            "system_state": {
                "core_heat": 10.0,
                "last_processed_timestamp": self.start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(initial_ledger, f)

        new_dna = "VOL00000000002"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', self.mock_mod):
            # Must raise ThermalOverloadError and include required UI message keys
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

            err_msg = str(ctx.exception)
            self.assertIn(UI_MESSAGES["refusal_reason"], err_msg)
            self.assertIn(UI_MESSAGES["next_action_hint"], err_msg)

            # Verify NO SILENT DRAINS: new DNA was not processed into ledger
            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)

            self.assertNotIn(new_dna, ledger, "Refused DNA sequence must not be recorded in ledger")
            self.assertGreaterEqual(ledger['system_state']['core_heat'], 10.0, "Core heat must remain locked without silent drains")

    def test_passive_cooling_dissipation(self):
        # Core heat was 10.0 10 seconds ago -> 10.0 - (10 * 0.5) = 5.0 core heat now
        past_time = (self.start_dt - datetime.timedelta(seconds=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
        initial_ledger = {
            "system_state": {
                "core_heat": 10.0,
                "last_processed_timestamp": past_time
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(initial_ledger, f)

        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', self.mock_mod):
            run_batch()

            with open(self.ledger_path, 'r') as f:
                ledger = json.load(f)

            # Heat dissipated from 10.0 to 5.0 over 10s, then +2.0 heat added by parse -> 7.0 core heat
            self.assertEqual(ledger['system_state']['core_heat'], 7.0)
            self.assertIn(dna, ledger)

if __name__ == '__main__':
    unittest.main()

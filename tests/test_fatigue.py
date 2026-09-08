import os
import sys
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    HEAT_PER_SEQUENCE,
    MAX_CORE_HEAT,
    COOLING_RATE_PER_SEC,
    REFUSAL_REASON_KEY,
    NEXT_ACTION_HINT_KEY,
    CONSEQUENCE_KEY
)

class MockDatetime:
    timezone = real_datetime.timezone

    class datetime:
        _current_time = real_datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.datetime.strptime(date_string, format_string)

        @classmethod
        def set_time(cls, dt):
            cls._current_time = dt

        @classmethod
        def advance_seconds(cls, seconds):
            cls._current_time = cls._current_time + real_datetime.timedelta(seconds=seconds)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.project_root, 'rules')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.datetime.set_time(real_datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_per_sequence(self):
        """Verify that each processed sequence increases core heat by 2.0 units."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertEqual(system_state.get('core_heat'), HEAT_PER_SEQUENCE)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_refusal_messages(self):
        """Verify that reaching safety lockout threshold triggers ThermalOverloadError with UI keys."""
        # 5 sequences * 2.0 heat = 10.0 heat (MAX_CORE_HEAT)
        dnas = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], MAX_CORE_HEAT)

        # Attempt to process another sequence when core heat is 10.0
        next_dna = "VOL08900750799"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(next_dna + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        error_message = str(cm.exception)
        self.assertIn(REFUSAL_REASON_KEY, error_message)
        self.assertIn(NEXT_ACTION_HINT_KEY, error_message)
        self.assertEqual(error_message, f"{REFUSAL_REASON_KEY}: {NEXT_ACTION_HINT_KEY}")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_dissipation_over_time(self):
        """Verify core heat cools down over time at 0.5 heat units / second."""
        # Process 5 sequences to reach 10.0 heat
        dnas = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        # Advance time by 10 seconds => dissipation = 10s * 0.5 = 5.0 heat units
        MockDatetime.datetime.advance_seconds(10)

        # Process a new sequence (heat will dissipate to 5.0, then add 2.0 -> 7.0 heat)
        new_dna = "VOL08900750799"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        expected_heat = (MAX_CORE_HEAT - (10 * COOLING_RATE_PER_SEC)) + HEAT_PER_SEQUENCE
        self.assertEqual(ledger_data['system_state']['core_heat'], expected_heat)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_silent_drains(self):
        """Verify that deduplicated sequences do not add heat, and lockout prevents clearing input file."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        initial_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(initial_heat, 2.0)

        # Re-run same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        # Core heat should remain unchanged because sequence was deduplicated
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data_after = json.load(f)
        self.assertEqual(ledger_data_after['system_state']['core_heat'], initial_heat)

        # Test process_once on thermal lockout does not clear input file
        ledger_data_after['system_state']['core_heat'] = 10.0
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger_data_after, f)

        new_dna = "VOL08900750799"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_dna + "\n")

        import main
        with patch('main.__file__', os.path.join(self.project_root, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file must NOT be cleared on refusal
        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), new_dna)


if __name__ == '__main__':
    unittest.main()

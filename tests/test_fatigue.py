import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    run_batch,
    load_ledger,
    save_ledger,
    ThermalOverloadError
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

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_idempotency(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger_dict, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], 2.0)

        # Idempotency run: double invocation with same DNA should hit deduplication and NOT add heat
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger_dict, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], 2.0)

    def test_thermal_dissipation(self):
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger_dict, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], 2.0)

        # Advance simulated time by 2 seconds (0.5 heat units / sec decay -> 1.0 unit decay -> remaining heat = 1.0)
        MockDatetime.current_time += datetime.timedelta(seconds=2)

        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        ledger_dict, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], 3.0)

    def test_thermal_overload_lockout_and_message_keys(self):
        # 6 distinct sequences = 12.0 heat units > 10.0 safety threshold
        dnas = [f"VOL089007507{i:02d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_no_silent_drains_on_thermal_overload(self):
        dnas = [f"VOL089007507{i:02d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        import main
        main.__file__ = os.path.join(self.project_root, 'main.py')

        with patch('utils.dna_ui.datetime', MockDatetime):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):
                    main.process_once()

                mock_clear.assert_not_called()

        with open(self.input_file, 'r') as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 6, "Input file must not be drained upon Thermal Lockout refusal.")

if __name__ == '__main__':
    unittest.main()

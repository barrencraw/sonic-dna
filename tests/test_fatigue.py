import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch

import utils.dna_ui as dna_ui
from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    MESSAGE_KEY_CONSEQUENCE,
    MESSAGE_KEY_REFUSAL_REASON,
    MESSAGE_KEY_NEXT_ACTION_HINT
)

class MockDatetimeModule:
    timezone = datetime.timezone

    class datetime:
        current_time = datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

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
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetimeModule.datetime.current_time = datetime.datetime(2026, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_heat_accumulation_and_decay(self):
        dnas = ["VOL08900750712", "VOL00000000000"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 4.0)

        # Advance simulated time by 4 seconds (0.5 heat/sec decay -> -2.0 heat, remaining = 2.0)
        MockDatetimeModule.datetime.current_time += datetime.timedelta(seconds=4)

        dna3 = "TIM00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna3 + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 4.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_thermal_lockout_refusal(self):
        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "TIM00000000000",
            "HAR00000000000",
            "FRE00000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, MESSAGE_KEY_CONSEQUENCE)
        self.assertEqual(err.refusal_reason, MESSAGE_KEY_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, MESSAGE_KEY_NEXT_ACTION_HINT)

        with open(self.json_output, 'r') as f:
            saved_output = json.load(f)
        self.assertEqual(len(saved_output), 4)

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(len(ledger_data['ledger']), 4)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_idempotency_does_not_add_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data1 = json.load(f)
        self.assertEqual(ledger_data1['system_state']['core_heat'], 2.0)

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data2 = json.load(f)

        self.assertEqual(ledger_data2['system_state']['core_heat'], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetimeModule)
    def test_no_silent_drains_on_lockout(self):
        import main

        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "TIM00000000000",
            "HAR00000000000",
            "FRE00000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with patch.object(main, '__file__', os.path.join(self.project_root, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertTrue(len(content) > 0)

if __name__ == '__main__':
    unittest.main()

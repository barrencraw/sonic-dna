import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock

import utils.dna_ui as dna_ui
from utils.dna_ui import main as run_batch, ThermalOverloadError, UI_MESSAGES

class MockDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls._mock_now

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

        initial_state = {
            'ledger': {},
            'system_state': {'core_heat': 0.0, 'last_processed_timestamp': None}
        }
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump(initial_state, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_lockout(self):
        """Test that operational heat accumulates per sequence and triggers ThermalOverloadError at limit."""
        # 5 distinct valid volume sequences (prefix VOL + valid subvars)
        sequences = ["VOL08900750712", "VOL00000000000", "VOL05005005000", "VOL01001001000", "VOL02002002000"]

        # Write 5 sequences -> Total heat will reach 10.0 (MAX_HEAT_LIMIT)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # 6th sequence will attempt to push heat to 12.0 > 10.0 -> ThermalOverloadError
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL03003003000\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, UI_MESSAGES["consequence_applied"])
        self.assertEqual(err.refusal_reason, UI_MESSAGES["refusal_reason"])
        self.assertEqual(err.next_action_hint, UI_MESSAGES["next_action_hint"])

    def test_idempotency_no_extra_heat(self):
        """Verify that double invocation / deduplicated sequences do NOT accumulate extra heat."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data1 = json.load(f)
        self.assertEqual(data1['system_state']['core_heat'], 2.0)

        # Second run with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data2 = json.load(f)
        # Heat should remain 2.0 (or decrease slightly if time elapsed, but not add +2.0)
        self.assertLessEqual(data2['system_state']['core_heat'], 2.0)

    def test_passive_thermal_decay(self):
        """Test deterministic passive heat decay over simulated elapsed time."""
        t0 = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # Initial run at t0 -> 2.0 heat
        MockDatetime._mock_now = t0
        mock_datetime_module = MagicMock()
        mock_datetime_module.datetime = MockDatetime
        mock_datetime_module.timezone = datetime.timezone

        with patch('utils.dna_ui.datetime', mock_datetime_module):
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write("VOL08900750712\n")
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # Advance time by 2 seconds (0.5 heat/sec decay -> decay = 1.0)
        t1 = t0 + datetime.timedelta(seconds=2)
        MockDatetime._mock_now = t1

        # Next run at t1: starting heat = 2.0 - 1.0 = 1.0. New operation + 2.0 = 3.0 heat
        with patch('utils.dna_ui.datetime', mock_datetime_module):
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write("VOL00000000000\n")
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data_t1 = json.load(f)
        self.assertEqual(data_t1['system_state']['core_heat'], 3.0)

if __name__ == '__main__':
    unittest.main()

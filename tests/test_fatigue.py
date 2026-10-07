import os
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class MockDatetime:
    tz = real_datetime.timezone.utc
    _now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=tz)

    class datetime:
        tz = real_datetime.timezone.utc
        _now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=tz)

        @classmethod
        def now(cls, tz=None):
            return cls._now

        @classmethod
        def strptime(cls, date_string, format_str):
            return real_datetime.datetime.strptime(date_string, format_str)

    timezone = real_datetime.timezone

class TestFatigueSystem(unittest.TestCase):
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

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_idempotency(self):
        """Proof: Heat increases exactly once per parsed sequence (+2.0). Deduplicated sequences generate 0 heat."""
        MockDatetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        MockDatetime.datetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        # Batch 1: 3 new DNA sequences -> expected +6.0 core heat
        dnas = ["VOL08900750712", "VOL00000000000", "TIM01020304050"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        full_ledger = load_ledger(self.ledger_path)
        self.assertEqual(full_ledger['system_state']['core_heat'], 6.0)

        # Batch 2: Invocation with duplicate sequences -> expected heat remains 6.0 (no duplicate heat drain)
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        full_ledger_after_dedupe = load_ledger(self.ledger_path)
        self.assertEqual(full_ledger_after_dedupe['system_state']['core_heat'], 6.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_overload_refusal_and_ui_keys(self):
        """Proof: Exceeding heat threshold (>10.0) raises ThermalOverloadError with required UI message keys."""
        MockDatetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        MockDatetime.datetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        # 6 sequences * 2.0 heat = 12.0 heat (breaches limit 10.0 on 6th sequence)
        dnas = [
            "VOL08900750712",
            "VOL00000000000",
            "TIM01020304050",
            "TIM00000000000",
            "VOL05005005005",
            "TIM05005005005"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_deterministic_cooling_no_silent_drains(self):
        """Proof: Cooling dissipates heat predictably over time without silent or arbitrary drains."""
        # Step 1: Accumulate 8.0 heat at T=0s (4 sequences)
        MockDatetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        MockDatetime.datetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        dnas1 = ["VOL08900750712", "VOL00000000000", "TIM01020304050", "TIM00000000000"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas1) + "\n")

        run_batch()
        full_ledger1 = load_ledger(self.ledger_path)
        self.assertEqual(full_ledger1['system_state']['core_heat'], 8.0)

        # Step 2: Advance time by 10 seconds (cooling = 10 * 0.5 = 5.0 heat dissipation)
        # Heat after dissipation: 8.0 - 5.0 = 3.0. Add 1 new sequence (+2.0) -> expected final heat = 5.0.
        MockDatetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 10, tzinfo=real_datetime.timezone.utc)
        MockDatetime.datetime._now = real_datetime.datetime(2026, 9, 14, 12, 0, 10, tzinfo=real_datetime.timezone.utc)
        dnas2 = ["VOL05005005005"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas2) + "\n")

        run_batch()
        full_ledger2 = load_ledger(self.ledger_path)
        self.assertEqual(full_ledger2['system_state']['core_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()

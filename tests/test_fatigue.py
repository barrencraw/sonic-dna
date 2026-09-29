import os
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    LOCKOUT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    HEAT_DISSIPATION_RATE,
    DNAStatus
)

class MockDatetime:
    current_dt = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_dt

        @classmethod
        def strptime(cls, date_string, format):
            return real_datetime.datetime.strptime(date_string, format)

        @classmethod
        def fromisoformat(cls, date_string):
            return real_datetime.datetime.fromisoformat(date_string)

    timezone = real_datetime.timezone

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

        MockDatetime.current_dt = real_datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_idempotency(self):
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        system_state = data['system_state']
        self.assertEqual(system_state['core_heat'], 4.0, "Processing 2 sequences should accumulate 4.0 heat units")

        # Second run with duplicate sequences
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna1}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 4.0, "Deduplicated sequence should not add core heat")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        # Accumulate 8.0 heat
        sequences = [f"VOL000000000{i}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 8.0)

        # Advance time by 10 seconds -> Decay = 10 * 0.5 = 5.0 units. Core heat should drop to 3.0.
        MockDatetime.current_dt += real_datetime.timedelta(seconds=10)

        new_seq = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Heat decayed to 3.0, then +2.0 from new_seq = 5.0
        self.assertAlmostEqual(data['system_state']['core_heat'], 5.0, places=2)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_refusal(self):
        # Process 5 sequences to reach 10.0 threshold
        sequences = [f"VOL000000000{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 10.0)

        # Next sequence should be refused with ThermalOverloadError
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL09900000000\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_overload(self):
        # Cause thermal overload
        sequences = [f"VOL000000000{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        unprocessed_seq = "VOL07700000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(unprocessed_seq + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check input file was not wiped/drained
        with open(self.input_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        self.assertEqual(content, unprocessed_seq, "Unprocessed input file must not be drained during thermal lockout")

        # Advance time by 20 seconds to allow mainframe cooling
        MockDatetime.current_dt += real_datetime.timedelta(seconds=20)

        # Retry - should now succeed
        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        ledger = data.get('ledger', data)
        self.assertIn(unprocessed_seq, ledger)
        self.assertEqual(ledger[unprocessed_seq]['terminal_outcome'], 'success')

    def test_ui_message_keys_and_enum(self):
        self.assertEqual(MSG_CONSEQUENCE_APPLIED, "Heat Accumulation")
        self.assertEqual(MSG_REFUSAL_REASON, "Thermal Lockout")
        self.assertEqual(MSG_NEXT_ACTION_HINT, "Wait for dissipation. The system is indifferent to your deadlines.")
        self.assertEqual(DNAStatus.SUCCESS.value, "success")
        self.assertEqual(DNAStatus.REFUSED.value, "refused")
        self.assertEqual(DNAStatus.SUCCESS.success, "success")
        self.assertEqual(DNAStatus.REFUSED.refused, "refused")

if __name__ == '__main__':
    unittest.main()

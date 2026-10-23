import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    main as run_batch,
    load_ledger,
    save_ledger,
    ThermalOverloadError,
    MAX_CORE_HEAT,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data folder if present
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger & state
        save_ledger(self.ledger_path, {}, {'core_heat': 0.0, 'last_processed_timestamp': None})

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_refusal(self):
        # 1. Prepare 6 DNA sequences -> total heat 6 * 2.0 = 12.0 (> 10.0 threshold)
        dna_sequences = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004"
        ]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, MSG_CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, MSG_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, MSG_NEXT_ACTION_HINT)
        self.assertIn(MSG_REFUSAL_REASON, str(err))
        self.assertIn(MSG_NEXT_ACTION_HINT, str(err))

    def test_heat_dissipation_and_idempotency(self):
        # Step A: Process 4 sequences -> heat = 8.0 (< 10.0)
        dna_sequences_step_1 = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002"
        ]

        start_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return start_time

        with patch('utils.dna_ui.datetime') as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.datetime = MockDatetime
            with open(self.input_file, 'w') as f:
                f.write("\n".join(dna_sequences_step_1) + "\n")

            run_batch()

        ledger, state = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 4)
        self.assertEqual(state['core_heat'], 8.0)

        # Step B: Double invocation with SAME sequences (idempotency check)
        # Should NOT add core heat or process anything new
        with patch('utils.dna_ui.datetime') as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.datetime = MockDatetime
            with open(self.input_file, 'w') as f:
                f.write("\n".join(dna_sequences_step_1) + "\n")

            run_batch()

        _, state_after_dedupe = load_ledger(self.ledger_path)
        self.assertEqual(state_after_dedupe['core_heat'], 8.0)

        # Step C: Advance time by 10 seconds -> dissipation = 10 * 0.5 = 5.0 -> core_heat becomes 3.0
        later_time = start_time + datetime.timedelta(seconds=10)

        class MockDatetimeLater(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return later_time

            @classmethod
            def strptime(cls, date_string, format_str):
                return datetime.datetime.strptime(date_string, format_str)

        new_sequence = ["VOL00000000003"] # Adds 2.0 heat -> new heat = 5.0

        with patch('utils.dna_ui.datetime') as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.datetime = MockDatetimeLater
            with open(self.input_file, 'w') as f:
                f.write("\n".join(new_sequence) + "\n")

            run_batch()

        ledger_final, state_final = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger_final), 5)
        self.assertEqual(state_final['core_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    UI_MSG_CONSEQUENCE,
    UI_MSG_REFUSAL_REASON,
    UI_MSG_NEXT_ACTION_HINT,
    MAX_HEAT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC
)

class MockDatetime:
    timezone = datetime.timezone
    _current_time = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime._current_time

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

    @classmethod
    def advance_seconds(cls, seconds):
        cls._current_time += datetime.timedelta(seconds=seconds)

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

        MockDatetime._current_time = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout_refusal(self):
        # Write sequences that reach heat limit (5 sequences * 2.0 heat = 10.0 heat)
        # Each sequence must be unique valid sequence
        seqs = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003"
        ]

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(seqs) + "\n")

        run_batch()

        # Check accumulated core heat in ledger
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            full_ledger = json.load(f)

        state = full_ledger.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 10.0)

        # Adding 6th sequence will exceed 10.0 threshold and trigger ThermalOverloadError
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL00000000004\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(UI_MSG_REFUSAL_REASON, err_msg)
        self.assertIn(UI_MSG_CONSEQUENCE, err_msg)
        self.assertIn(UI_MSG_NEXT_ACTION_HINT, err_msg)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_zero_heat_on_dedupe_hit(self):
        seq = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            full_ledger = json.load(f)
        initial_heat = full_ledger['system_state']['core_heat']
        self.assertEqual(initial_heat, 2.0)

        # Reprocess same sequence (deduplication hit)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            full_ledger = json.load(f)
        new_heat = full_ledger['system_state']['core_heat']
        self.assertEqual(new_heat, initial_heat, "Deduplicated sequence must add 0 core heat")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_dissipation_over_time(self):
        # Accumulate 10.0 heat
        seqs = [f"VOL0000000000{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(seqs) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            full_ledger = json.load(f)
        self.assertEqual(full_ledger['system_state']['core_heat'], 10.0)

        # Advance simulated time by 10 seconds -> dissipation = 10 * 0.5 = 5.0 heat units
        MockDatetime.advance_seconds(10)

        # Now run new sequence: starting heat will be 5.0 + 2.0 = 7.0 heat
        new_seq = "VOL09999999999"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_seq + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            full_ledger = json.load(f)
        self.assertEqual(full_ledger['system_state']['core_heat'], 7.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_lockout(self):
        # Fill heat to 10.0
        seqs = [f"VOL000000000{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(seqs) + "\n")

        run_batch()

        # Add additional sequence that causes lockout
        extra_seq = "VOL0000000099"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(extra_seq + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Input file remains untouched (no silent drain/deletion)
        with open(self.input_file, 'r', encoding='utf-8') as f:
            contents = f.read().strip()
        self.assertEqual(contents, extra_seq)

if __name__ == '__main__':
    unittest.main()

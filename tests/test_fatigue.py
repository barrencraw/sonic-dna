import os
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError, UI_MESSAGES, HEAT_PER_SEQUENCE, LOCKOUT_THRESHOLD

class MockDatetime:
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return real_datetime.datetime.strptime(date_string, format_spec)

    timezone = real_datetime.timezone

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

        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({
                "ledger": {},
                "system_state": {
                    "core_heat": 0.0,
                    "last_processed_timestamp": None
                }
            }, f)

        MockDatetime.current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_decay(self):
        # 1. First sequence adds 2.0 heat
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna1}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)

        # 2. Advance time by 2 seconds (2s * 0.5 decay/sec = 1.0 decay)
        MockDatetime.current_time += real_datetime.timedelta(seconds=2)

        dna2 = "VOL00000000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna2}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        # 2.0 - 1.0 + 2.0 = 3.0 heat
        self.assertAlmostEqual(ledger_data["system_state"]["core_heat"], 3.0, places=2)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_refusal(self):
        # 5 sequences in burst = 10.0 heat -> hits lockout threshold
        dna_sequences = [f"VOL00{i}00000000" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dna_sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 10.0)

        # 6th sequence should trigger ThermalOverloadError
        dna6 = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna6}\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(UI_MESSAGES["REFUSAL_REASON"], err_msg)
        self.assertIn(UI_MESSAGES["NEXT_ACTION_HINT"], err_msg)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_heat_addition(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        initial_heat = ledger_data["system_state"]["core_heat"]

        # Run second time with same DNA sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data["system_state"]["core_heat"], initial_heat)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_overload(self):
        # Fill heat to 10.0
        dna_sequences = [f"VOL00{i}00000000" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dna_sequences) + "\n")

        run_batch()

        # Place new DNA sequence in input file
        new_dna = "VOL09900000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{new_dna}\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify input file content remains intact (no silent drain)
        with open(self.input_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        self.assertEqual(content, new_dna)

if __name__ == '__main__':
    unittest.main()

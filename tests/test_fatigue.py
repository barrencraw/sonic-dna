import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, UI_MESSAGES

class MockDatetime:
    current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
    timezone = datetime.timezone

    class datetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def fromisoformat(cls, date_string):
            return datetime.datetime.fromisoformat(date_string)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data folder if present
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        MockDatetime.current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_idempotency(self):
        """Test that heat accumulates on new sequences and is applied exactly once (no silent drains on duplicate)."""
        dna = "VOL08900750712"

        # 1. First invocation adds +2.0 heat
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn("system_state", ledger_data)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)
        self.assertIn(dna, ledger_data["ledger"])

        # 2. Second invocation with same DNA (deduplicated)
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data_2 = json.load(f)

        # Core heat should remain 2.0 (applied exactly once, no silent heat drain on dedupe hit)
        self.assertEqual(ledger_data_2["system_state"]["core_heat"], 2.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_no_silent_drains(self):
        """Test lockout enforcement at >= 10.0 heat units and UI message key propagation."""
        dnas = [
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004",
            "VOL00000000005", # 5th sequence -> heat reaches 10.0
            "VOL00000000006"  # 6th sequence -> refused due to lockout
        ]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        self.assertIn(UI_MESSAGES["refusal_reason"], err_msg)
        self.assertIn(UI_MESSAGES["next_action_hint"], err_msg)

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # Check core heat is capped/tracked at 10.0
        self.assertEqual(ledger_data["system_state"]["core_heat"], 10.0)
        # Check that the first 5 sequences were processed successfully
        for dna in dnas[:5]:
            self.assertIn(dna, ledger_data["ledger"])
        # Check that 6th sequence was refused and not logged as success
        self.assertNotIn(dnas[5], ledger_data["ledger"])

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_dissipation_over_time(self):
        """Test that cooling occurs at 0.5 heat units / second over time."""
        dnas = ["VOL00000000001", "VOL00000000002", "VOL00000000003", "VOL00000000004"] # 4 * 2.0 = 8.0 heat

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 8.0)

        # Simulate 10 seconds of time passing (10s * 0.5 heat/s = 5.0 heat dissipated)
        MockDatetime.current_time += datetime.timedelta(seconds=10)

        new_dna = "VOL00000000005"
        with open(self.input_file, 'w') as f:
            f.write(f"{new_dna}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data_after = json.load(f)

        # Expected core heat: max(0, 8.0 - 5.0) + 2.0 = 5.0
        self.assertEqual(ledger_data_after["system_state"]["core_heat"], 5.0)


if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    THERMAL_MESSAGE_KEYS,
    LOCKOUT_THRESHOLD,
    HEAT_PER_ITEM,
    COOLING_RATE_PER_SEC
)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data folder if present
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean test state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize clean ledger
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_idempotency_heat_applied_exactly_once(self):
        """Verify that heat is applied exactly once for new items and deduplicated items add zero heat."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        base_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return base_time

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        state = ledger.get("system_state", {})
        self.assertEqual(state.get("core_heat"), HEAT_PER_ITEM)

        # Re-run same DNA string at the exact same timestamp
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger2 = json.load(f)

        state2 = ledger2.get("system_state", {})
        self.assertEqual(state2.get("core_heat"), HEAT_PER_ITEM, "Deduplicated run should NOT add additional core heat.")

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        """Verify thermal lockout raises exception with message keys and no silent drains occur."""
        # 5 distinct DNA sequences will try to accumulate 5 * 2.0 = 10.0 heat.
        # Since threshold is 10.0, the 6th item (or 5th when threshold reached) triggers lockout refusal.
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            for dna in dnas:
                f.write(f"{dna}\n")

        base_time = datetime.datetime(2025, 6, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return base_time

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, THERMAL_MESSAGE_KEYS["consequence_applied"])
        self.assertEqual(err.refusal_reason, THERMAL_MESSAGE_KEYS["refusal_reason"])
        self.assertEqual(err.next_action_hint, THERMAL_MESSAGE_KEYS["next_action_hint"])

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        state = ledger.get("system_state", {})
        self.assertGreaterEqual(state.get("core_heat", 0.0), LOCKOUT_THRESHOLD)

        # Verify heat dissipation over time resets system for processing
        later_time = base_time + datetime.timedelta(seconds=25) # 25s * 0.5 = 12.5 heat dissipated
        class MockLaterDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return later_time

        # Single new DNA string after cooling
        cooling_dna = "VOL08900750799"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{cooling_dna}\n")

        with patch('utils.dna_ui.datetime.datetime', MockLaterDatetime):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_after = json.load(f)

        self.assertIn(cooling_dna, ledger_after)
        state_after = ledger_after.get("system_state", {})
        self.assertEqual(state_after.get("core_heat"), HEAT_PER_ITEM)

if __name__ == '__main__':
    unittest.main()

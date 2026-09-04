import sys
from unittest.mock import MagicMock

# Mock dependencies if not present in test environment
sys.modules["sounddevice"] = sys.modules.get("sounddevice", MagicMock())

import os
import json
import shutil
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    HEAT_PER_SEQUENCE,
    HEAT_DISSIPATION_RATE,
    MAX_HEAT_THRESHOLD,
    CONSEQUENCE_APPLIED_KEY,
    REFUSAL_REASON_KEY,
    NEXT_ACTION_HINT_KEY,
)

class MockDatetime(datetime):
    current_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def advance(cls, seconds):
        cls.current_time += timedelta(seconds=seconds)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize clean ledger
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

        MockDatetime.current_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_decay(self):
        # Process 2 sequences => 4.0 heat units accumulated
        dna_batch = ["VOL08900750712\n", "VOL00000000000\n"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.writelines(dna_batch)

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        state = ledger.get('_system_state', {})
        self.assertEqual(state.get('core_heat'), 4.0)

        # Advance simulated time by 4 seconds => decay 4 * 0.5 = 2.0 heat units (leaving 2.0 heat units)
        MockDatetime.advance(4)

        # Process 1 new sequence => cost 2.0 => current core heat becomes 2.0 + 2.0 = 4.0
        new_dna = "VOL10000000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        state = ledger.get('_system_state', {})
        self.assertEqual(state.get('core_heat'), 4.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_and_message_keys(self):
        # Max threshold = 10.0. 6 sequences = 12.0 heat => triggers ThermalOverloadError
        dna_batch = [f"VOL000000000{i}\n" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.writelines(dna_batch)

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, CONSEQUENCE_APPLIED_KEY)
        self.assertEqual(err.refusal_reason, REFUSAL_REASON_KEY)
        self.assertEqual(err.next_action_hint, NEXT_ACTION_HINT_KEY)
        self.assertIn(REFUSAL_REASON_KEY, str(err))
        self.assertIn(NEXT_ACTION_HINT_KEY, str(err))

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_does_not_accumulate_heat(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        self.assertEqual(ledger.get('_system_state', {}).get('core_heat'), 2.0)

        # Second run with same DNA
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        # Core heat must remain 2.0, not increase to 4.0
        self.assertEqual(ledger.get('_system_state', {}).get('core_heat'), 2.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains_on_refusal(self):
        # Set core heat close to threshold in ledger
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({
                '_system_state': {
                    'core_heat': 9.0,
                    'last_processed_timestamp': MockDatetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                }
            }, f)

        # 1 new sequence (cost 2.0) => 9.0 + 2.0 = 11.0 > 10.0 threshold
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        import main
        with patch('main.clear_input_file') as mock_clear:
            with self.assertRaises(SystemExit):
                main.process_once()
            mock_clear.assert_not_called()

        # Verify raw input file was preserved (no silent drain)
        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), dna)

        # Verify output JSON was NOT created
        self.assertFalse(os.path.exists(self.json_output))

if __name__ == '__main__':
    unittest.main()

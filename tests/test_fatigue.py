import os
import json
import shutil
import sys
import unittest
import datetime
from unittest.mock import patch, MagicMock

# Ensure PySide6/sounddevice mocks if needed
try:
    import sounddevice
except ImportError:
    sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    LOCKOUT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    DISSIPATION_RATE,
    CONSEQUENCE_APPLIED,
    REFUSAL_REASON,
    NEXT_ACTION_HINT
)
import main as main_entry

class MockDatetime:
    timezone = datetime.timezone
    current_time = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format_spec):
            return datetime.datetime.strptime(date_string, format_spec)


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

        MockDatetime.current_time = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        """Verify that newly processed sequences accumulate heat (+2.0 each) and lockout triggers at threshold 10.0."""
        # 5 valid sequences (VOL prefix with valid subvar ranges)
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        state = ledger_data.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 10.0, "5 sequences should accumulate exactly 10.0 heat units")

        # 6th sequence should trigger ThermalOverloadError
        extra_seq = "VOL08900750715"
        with open(self.input_file, 'w') as f:
            f.write(f"{extra_seq}\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.refusal_reason, REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, NEXT_ACTION_HINT)
        self.assertGreaterEqual(err.current_heat, LOCKOUT_THRESHOLD)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_heat_accumulation(self):
        """Verify that duplicate/already-processed sequences do NOT accumulate core heat."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        heat_after_first = ledger_data.get('system_state', {}).get('core_heat')
        self.assertEqual(heat_after_first, 2.0)

        # Run same DNA sequence again
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        heat_after_second = ledger_data.get('system_state', {}).get('core_heat')
        self.assertEqual(heat_after_second, 2.0, "Deduplicated hits must not add heat")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        """Verify core heat dissipates at 0.5 units/sec over elapsed time."""
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        # Advance time by 10 seconds (10s * 0.5 = 5.0 heat dissipated)
        MockDatetime.current_time += datetime.timedelta(seconds=10)

        new_seq = "VOL08900750715"
        with open(self.input_file, 'w') as f:
            f.write(f"{new_seq}\n")

        # Processing should now succeed since heat dropped from 10.0 to 5.0, then +2.0 = 7.0
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        state = ledger_data.get('system_state', {})
        self.assertEqual(state.get('core_heat'), 7.0, "Heat should dissipate by 5.0 and then add 2.0")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains(self):
        """Verify that when ThermalOverloadError is raised, main.process_once does not clear the input file."""
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")
        run_batch() # core_heat = 10.0

        extra_seq = "VOL08900750715"
        with open(self.input_file, 'w') as f:
            f.write(f"{extra_seq}\n")

        with self.assertRaises(SystemExit):
            main_entry.process_once()

        # Check that toSequence.txt was NOT cleared
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, extra_seq, "Input file must be preserved on refusal (no silent drains)")


if __name__ == '__main__':
    unittest.main()

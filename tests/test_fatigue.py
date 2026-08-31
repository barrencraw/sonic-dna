import os
import json
import shutil
import unittest
import datetime as real_datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    load_ledger,
    ThermalOverloadError,
    UI_CONSEQUENCE_APPLIED,
    UI_REFUSAL_REASON,
    UI_NEXT_ACTION_HINT,
    LOCKOUT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC
)

class MockDatetime:
    current_time = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetime.current_time

        @classmethod
        def strptime(cls, date_string, format):
            return real_datetime.datetime.strptime(date_string, format)

    timezone = real_datetime.timezone

    @classmethod
    def set_time(cls, dt):
        cls.current_time = dt

    @classmethod
    def advance(cls, seconds):
        cls.current_time += real_datetime.timedelta(seconds=seconds)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Reset mock time
        MockDatetime.set_time(real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc))

        # Initialize clean ledger file
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': '2026-03-02T12:00:00Z'}}, f)

        self.datetime_patcher = patch('utils.dna_ui.datetime', MockDatetime)
        self.datetime_patcher.start()

    def tearDown(self):
        self.datetime_patcher.stop()
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        """Each new sequence adds HEAT_PER_SEQUENCE heat units."""
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        entries, system_state = load_ledger(self.ledger_path)
        self.assertIn(dna1, entries)
        self.assertIn(dna2, entries)
        self.assertEqual(system_state['core_heat'], 2 * HEAT_PER_SEQUENCE)

    def test_idempotency_no_heat_accumulation(self):
        """Duplicate DNA sequences do NOT accumulate heat on re-execution."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()
        _, state1 = load_ledger(self.ledger_path)
        self.assertEqual(state1['core_heat'], HEAT_PER_SEQUENCE)

        # Re-run same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()
        _, state2 = load_ledger(self.ledger_path)
        self.assertEqual(state2['core_heat'], HEAT_PER_SEQUENCE, "Core heat must not increase on duplicate sequence")

    def test_thermal_lockout_threshold(self):
        """Reaching core_heat >= LOCKOUT_THRESHOLD triggers ThermalOverloadError with UI keys."""
        # Process 5 sequences = 10.0 heat units
        sequences = [f"VOL0890075071{i}" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sequences) + '\n')

        run_batch()

        _, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], LOCKOUT_THRESHOLD)

        # Process a 6th sequence, triggering Thermal Lockout refusal
        next_seq = "VOL08900750799"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{next_seq}\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, UI_CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, UI_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, UI_NEXT_ACTION_HINT)
        self.assertIn(UI_REFUSAL_REASON, str(err))
        self.assertIn(UI_NEXT_ACTION_HINT, str(err))

    def test_heat_dissipation_over_time(self):
        """Heat dissipates at COOLING_RATE_PER_SEC when time elapses."""
        # Add 8.0 heat units
        sequences = [f"VOL0890075071{i}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sequences) + '\n')

        run_batch()

        _, state = load_ledger(self.ledger_path)
        self.assertEqual(state['core_heat'], 8.0)

        # Advance mock time by 10 seconds: 10s * 0.5 units/s = 5.0 units dissipated -> remaining 3.0
        MockDatetime.advance(10.0)

        # Add 1 new sequence: remaining (3.0) + 2.0 = 5.0 heat units
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL00000000000\n")

        run_batch()

        _, state_after = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state_after['core_heat'], 5.0, places=2)

    def test_no_silent_drains(self):
        """Thermal Overload exceptions are explicitly raised, ensuring no silent drains."""
        # Set initial core heat directly to lockout limit
        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({
                'ledger': {},
                'system_state': {'core_heat': 10.0, 'last_processed_timestamp': '2026-03-02T12:00:00Z'}
            }, f)

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()


if __name__ == '__main__':
    unittest.main()

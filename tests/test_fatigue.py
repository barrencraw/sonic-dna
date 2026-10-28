import os
import json
import shutil
import unittest
import tempfile
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    HEAT_PER_SEQUENCE,
    HEAT_LOCKOUT_THRESHOLD,
    DISSIPATION_RATE
)

class MockDatetimeModule:
    class datetime:
        _current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def strptime(cls, date_string, format_str):
            return datetime.datetime.strptime(date_string, format_str)

        timezone = datetime.timezone

    timezone = datetime.timezone


class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a minimal Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset mock time to fixed baseline
        MockDatetimeModule.datetime._current_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_accumulation_and_lockout(self):
        """Test heat accumulates per sequence and raises ThermalOverloadError upon threshold reach."""
        # HEAT_PER_SEQUENCE = 2.0, HEAT_LOCKOUT_THRESHOLD = 10.0
        # 5 sequences = 10.0 heat -> 6th sequence will hit threshold
        sequences = [f"VOL{i:03d}00000000" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

            err = cm.exception
            self.assertEqual(err.consequence, "Heat Accumulation")
            self.assertEqual(err.refusal_reason, "Thermal Lockout")
            self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check ledger state persisted up to overload point
        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)

        sys_state = ledger.get('_system_state', {})
        self.assertGreaterEqual(sys_state.get('core_heat', 0.0), HEAT_LOCKOUT_THRESHOLD)

    def test_idempotency_no_duplicate_heat_accumulation(self):
        """Test processing duplicate/already processed DNA produces zero additional heat and no double drain."""
        dna = "VOL100000000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_1 = json.load(f)

        heat_1 = ledger_1['_system_state']['core_heat']
        self.assertEqual(heat_1, HEAT_PER_SEQUENCE)

        # Re-run same batch immediately (deduplication hit)
        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_2 = json.load(f)

        heat_2 = ledger_2['_system_state']['core_heat']
        # Heat should remain identical because duplicate sequence was skipped
        self.assertEqual(heat_1, heat_2)

    def test_thermal_dissipation_over_time(self):
        """Test that heat dissipates over elapsed time allowing processing after lockout."""
        # 5 items to reach max heat 10.0
        sequences = [f"VOL{i:03d}00000000" for i in range(5)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['_system_state']['core_heat'], 10.0)

        # 6th new sequence will be refused right now
        new_dna = "VOL99900000"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Advance mock time by 10 seconds (dissipates 10 * 0.5 = 5.0 heat units)
        MockDatetimeModule.datetime._current_time += datetime.timedelta(seconds=10)

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()  # Should succeed now that heat decayed to 5.0 + 2.0 = 7.0

        with open(self.ledger_path, 'r', encoding='utf-8') as f:
            ledger_after = json.load(f)

        self.assertIn(new_dna, ledger_after)
        self.assertEqual(ledger_after['_system_state']['core_heat'], 7.0)

if __name__ == '__main__':
    unittest.main()

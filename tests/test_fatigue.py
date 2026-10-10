import os
import sys
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    HEAT_PER_SEQUENCE,
    THERMAL_LOCKOUT_THRESHOLD
)

class TestThermalFatigue(unittest.TestCase):
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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Create valid volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_fatigue_accumulation_and_lockout(self):
        """Verify heat accumulation, lockout refusal, message keys, and idempotency (no silent drains)."""
        # 5 valid sequences -> each adds 2.0 heat units -> hits 10.0 threshold at 5th sequence
        dnas = [f"VOL{i:03d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        initial_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetimeModule:
            timezone = datetime.timezone
            class datetime(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return initial_time
                @classmethod
                def strptime(cls, date_string, format_spec):
                    return datetime.datetime.strptime(date_string, format_spec)

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, MSG_CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, MSG_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, MSG_NEXT_ACTION_HINT)
        self.assertIn(MSG_REFUSAL_REASON, str(err))

        # Check ledger system state
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], THERMAL_LOCKOUT_THRESHOLD)
        # Exactly 5 items processed before lockout
        self.assertEqual(len(ledger_data['ledger']), 5)

        # Re-running immediately without waiting causes immediate lockout refusal (no new heat added, no silent drain)
        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Heat dissipates after cooling period (0.5 heat units/sec -> 10.0 units dissipates in 20 seconds)
        cooled_time = initial_time + datetime.timedelta(seconds=10) # dissipates 5.0 heat units, leaving 5.0
        class CooledDatetimeModule:
            timezone = datetime.timezone
            class datetime(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return cooled_time
                @classmethod
                def strptime(cls, date_string, format_spec):
                    return datetime.datetime.strptime(date_string, format_spec)

        # Try processing remaining 6th sequence (VOL005)
        with patch('utils.dna_ui.datetime', CooledDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            updated_ledger = json.load(f)

        self.assertIn('VOL005', updated_ledger['ledger'])
        self.assertEqual(len(updated_ledger['ledger']), 6)
        # 5.0 remaining heat + 2.0 added = 7.0 heat units
        self.assertAlmostEqual(updated_ledger['system_state']['core_heat'], 7.0)

    def test_idempotency_no_heat_drain_on_duplicates(self):
        """Verify that duplicate/already processed DNA sequences produce zero core heat accumulation."""
        dna = "VOL001"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        initial_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetimeModule:
            timezone = datetime.timezone
            class datetime(datetime.datetime):
                @classmethod
                def now(cls, tz=None):
                    return initial_time
                @classmethod
                def strptime(cls, date_string, format_spec):
                    return datetime.datetime.strptime(date_string, format_spec)

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], HEAT_PER_SEQUENCE)

        # Run again immediately with same DNA at same timestamp
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            updated_ledger = json.load(f)
        # Heat should NOT accumulate on duplicate hit
        self.assertAlmostEqual(updated_ledger['system_state']['core_heat'], HEAT_PER_SEQUENCE)

if __name__ == '__main__':
    unittest.main()

import unittest
import os
import json
import shutil
import tempfile
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    THERMAL_LOCKOUT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC
)

class MockDatetimeModule:
    class timezone:
        utc = datetime.timezone.utc

    def __init__(self, start_dt):
        self._current_dt = start_dt

    def advance(self, seconds):
        self._current_dt += datetime.timedelta(seconds=seconds)

    @property
    def datetime(self):
        m_self = self
        class _InnerDatetime:
            @classmethod
            def now(cls, tz=None):
                return m_self._current_dt

            @classmethod
            def strptime(cls, date_string, format_string):
                return datetime.datetime.strptime(date_string, format_string)

        return _InnerDatetime

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
        self.json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Copy real rules or create valid rules_Volume.json
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 1000, "pad": 4},
                    "lr": {"description": "lr", "min": 0, "max": 100, "pad": 3},
                    "sur": {"description": "surround", "min": 0, "max": 10, "pad": 2},
                    "head": {"description": "headroom", "min": 0, "max": 60, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        self.start_dt = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
        self.mock_dt_mod = MockDatetimeModule(self.start_dt)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_state_persistence(self):
        """Verify each new sequence adds 2.0 heat units."""
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nVOL08900750713\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        self.assertAlmostEqual(system_state.get('core_heat', 0.0), 4.0)

        # Check outcomes are success
        ledger = ledger_data.get('ledger', {})
        self.assertEqual(ledger['VOL08900750712']['terminal_outcome'], 'success')

    def test_thermal_dissipation_over_time(self):
        """Verify heat decays at 0.5 units/second over time."""
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nVOL08900750713\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            run_batch()

        # Advance 4 seconds => 4.0 - (4 * 0.5) = 2.0 heat remaining before next run
        self.mock_dt_mod.advance(4)

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750714\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        system_state = ledger_data.get('system_state', {})
        # 2.0 remaining + 2.0 for 1 new seq = 4.0
        self.assertAlmostEqual(system_state.get('core_heat', 0.0), 4.0)

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        """Verify lockout at >10.0 heat raises ThermalOverloadError and does not commit parsed output."""
        # 6 sequences = 12.0 heat > 10.0 threshold
        sequences = [f"VOL089007507{10+i}" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_CONSEQUENCE_APPLIED, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Confirm JSON output file was NOT created (no silent drain or partial commit)
        self.assertFalse(os.path.exists(self.json_out))

    def test_idempotency_deduplication_adds_zero_heat(self):
        """Verify double invocation of deduplicated sequence adds 0 heat."""
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            run_batch() # 1 seq => 2.0 heat

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 2.0)

        # Run again with same sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        with patch('utils.dna_ui.datetime', self.mock_dt_mod):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        # Deduplicated => 0 heat added
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 2.0)

if __name__ == '__main__':
    unittest.main()

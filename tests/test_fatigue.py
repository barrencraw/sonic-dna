import unittest
import os
import json
import shutil
import tempfile
from datetime import datetime as real_datetime, timezone, timedelta
from unittest.mock import patch

import utils.dna_ui
from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    UI_MESSAGES,
    DNAStatus
)

class MockDatetimeModule:
    class datetime:
        _now = real_datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._now

        @classmethod
        def strptime(cls, date_string, format_spec):
            return real_datetime.strptime(date_string, format_spec)

        @classmethod
        def set_now(cls, dt):
            cls._now = dt

        @classmethod
        def advance_seconds(cls, seconds):
            cls._now = cls._now + timedelta(seconds=seconds)

    timezone = timezone

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

        # Copy rules from project root
        project_rules = os.path.join(os.getcwd(), 'rules')
        if os.path.exists(project_rules):
            for f in os.listdir(project_rules):
                if f.endswith('.json'):
                    shutil.copy(os.path.join(project_rules, f), os.path.join(self.rules_dir, f))

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        MockDatetimeModule.datetime.set_now(real_datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc))

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_idempotency(self):
        """Prove heat accumulates +2.0 per sequence, and deduplicated sequences do NOT double-accumulate heat."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch()

        # Check ledger system state
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)
        self.assertEqual(ledger_data['ledger'][sequence]['terminal_outcome'], DNAStatus.SUCCESS)

        # Re-run same sequence (Idempotency check)
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # Heat should still be 2.0 (no double-accumulation on skipped sequence)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    def test_thermal_dissipation_over_time(self):
        """Prove core heat dissipates at 0.5 units per second over simulated time."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch() # Core heat = 2.0

        # Advance simulated time by 4 seconds (0.5 * 4 = 2.0 heat dissipated)
        MockDatetimeModule.datetime.advance_seconds(4.0)

        seq2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(seq2 + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        # Heat dissipated 2.0 -> 0.0, then seq2 added +2.0 -> final heat 2.0
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

    def test_thermal_lockout_refusal_and_ui_message_keys(self):
        """Prove processing 5 sequences reaches 10.0 threshold and 6th sequence triggers lockout refusal with UI message keys."""
        # 5 distinct valid volume sequences
        seqs = [
            "VOL00000000000",
            "VOL01000000000",
            "VOL02000000000",
            "VOL03000000000",
            "VOL04000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch() # 5 * 2.0 = 10.0 heat

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

        # Attempt 6th sequence -> should be refused with ThermalOverloadError
        seq6 = "VOL05000000000"
        with open(self.input_file, 'w') as f:
            f.write(seq6 + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err_msg = str(cm.exception)
        self.assertIn(UI_MESSAGES["refusal_reason"], err_msg)
        self.assertIn(UI_MESSAGES["next_action_hint"], err_msg)

        # Verify UI message key constants
        self.assertEqual(UI_MESSAGES["consequence_applied"], "Heat Accumulation")
        self.assertEqual(UI_MESSAGES["refusal_reason"], "Thermal Lockout")
        self.assertEqual(UI_MESSAGES["next_action_hint"], "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_no_silent_drains_on_lockout(self):
        """Prove that on thermal lockout refusal, the exception prevents clearing the input file (no silent drains)."""
        # Fill heat to 10.0
        seqs = [f"VOL00{i:02d}0000000" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            run_batch()

        # Place new sequence in input file
        blocked_seq = "VOL09900000000"
        with open(self.input_file, 'w') as f:
            f.write(blocked_seq + "\n")

        if 'main' in os.sys.modules:
            del os.sys.modules['main']
        import main

        sandbox_main_file = os.path.join(self.test_dir, 'main.py')
        with patch('utils.dna_ui.datetime', MockDatetimeModule.datetime):
            with patch.object(main, '__file__', sandbox_main_file):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()

                    mock_clear.assert_not_called()

        # Input file remains intact with blocked_seq
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), blocked_seq)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import tempfile
from datetime import datetime as real_datetime, timezone as real_timezone, timedelta
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)


class MockDatetime:
    current_time = real_datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current_time

    @classmethod
    def strptime(cls, date_string, format_string):
        return real_datetime.strptime(date_string, format_string)

    @classmethod
    def advance(cls, seconds):
        cls.current_time += timedelta(seconds=seconds)

    @classmethod
    def reset(cls):
        cls.current_time = real_datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_timezone.utc)


class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        MockDatetime.reset()
        self.test_dir = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.test_dir, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(self.rules_folder, exist_ok=True)

        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_folder, 'processed_ledger.json')

        # Create a mock rule for Volume ('VOL')
        vol_rule_path = os.path.join(self.rules_folder, 'rules_Volume.json')
        with open(vol_rule_path, 'w', encoding='utf-8') as f:
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

    def test_heat_accumulation_and_thermal_lockout(self):
        """
        Verify heat accumulates (+2.0/seq) up to threshold (10.0),
        and exceeding threshold triggers ThermalOverloadError with UI message keys.
        """
        # Create 6 sequences (5 * 2.0 = 10.0 heat, 6th sequence will exceed limit)
        sequences = [f"VOL{i:03d}" for i in range(1, 7)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sequences) + '\n')

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

            err_msg = str(ctx.exception)
            self.assertIn(MSG_REFUSAL_REASON, err_msg)
            self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Verify ledger recorded 5 successful sequences and core heat at 10.0
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        ledger = data.get('ledger', data)
        system_state = data.get('system_state', {})

        self.assertEqual(len(ledger), 5)
        self.assertEqual(system_state.get('core_heat'), 10.0)

        # Check UI message key recorded in ledger consequence
        for seq in sequences[:5]:
            self.assertIn(seq, ledger)
            self.assertEqual(ledger[seq].get('consequence'), MSG_CONSEQUENCE_APPLIED)

    def test_heat_dissipation_over_time(self):
        """
        Verify that core heat dissipates at 0.5 heat units per second, allowing execution to resume.
        """
        # Process 5 sequences -> 10.0 core heat
        sequences = [f"VOL{i:03d}" for i in range(1, 6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(sequences) + '\n')

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 10.0)

        # Advance simulated time by 4.0 seconds -> 4.0 * 0.5 = 2.0 heat dissipated -> 8.0 heat remaining
        MockDatetime.advance(4)

        # Now processing 1 new sequence (VOL006) should succeed (8.0 + 2.0 = 10.0 heat)
        new_sequence = "VOL006"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(new_sequence + '\n')

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        ledger = data.get('ledger', data)
        self.assertIn(new_sequence, ledger)
        self.assertEqual(data['system_state']['core_heat'], 10.0)

    def test_idempotency_applied_exactly_once(self):
        """
        Verify re-processing previously processed DNA sequence does not accumulate additional heat.
        """
        seq = "VOL001"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + '\n')

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        initial_heat = data['system_state']['core_heat']
        self.assertEqual(initial_heat, 2.0)

        # Re-run batch with same sequence
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(seq + '\n')

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Heat should remain unchanged (2.0) because sequence was deduplicated
        self.assertEqual(data['system_state']['core_heat'], 2.0)

    def test_no_silent_drains_on_thermal_overload(self):
        """
        Verify that when ThermalOverloadError occurs, the input file (toSequence.txt)
        is preserved by main.py exception handling so no data is silently lost.
        """
        import main

        sequences = [f"VOL{i:03d}" for i in range(1, 7)]
        input_content = '\n'.join(sequences) + '\n'
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(input_content)

        # Patch run_batch to simulate ThermalOverloadError as would happen inside main.py
        with patch('main.run_batch', side_effect=ThermalOverloadError(f"{MSG_REFUSAL_REASON}: Core heat limit exceeded. {MSG_NEXT_ACTION_HINT}")):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):
                    main.process_once()

                mock_clear.assert_not_called()

        # Confirm toSequence.txt still contains the unprocessed content
        with open(self.input_file, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), input_content)


if __name__ == '__main__':
    unittest.main()

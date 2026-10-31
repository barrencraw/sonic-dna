import os
import json
import shutil
import unittest
import tempfile
import datetime
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    MAX_HEAT_THRESHOLD,
    HEAT_PER_SEQUENCE,
    DISSIPATION_RATE_PER_SEC
)

class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.project_root = tempfile.mkdtemp()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.rules_folder = os.path.join(self.project_root, 'rules')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        os.makedirs(self.rules_folder, exist_ok=True)

        # Mock Volume rule
        rule_file = os.path.join(self.rules_folder, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.project_root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.project_root)

    def test_heat_accumulation_and_idempotency_no_duplicate_heat(self):
        """
        Verify that processing sequences accumulates heat deterministically,
        and double-invocation of the same sequence (idempotency) does NOT accumulate extra heat.
        """
        base_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetimeModule:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return base_time
                @classmethod
                def fromisoformat(cls, date_string):
                    return datetime.datetime.fromisoformat(date_string)

        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertEqual(ledger_data['system_state']['core_heat'], HEAT_PER_SEQUENCE)
        self.assertIn(dna, ledger_data['ledger'])

        # Now invoke again with the exact same DNA string (idempotency check)
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data2 = json.load(f)

        # Heat must NOT increase on duplicate processing
        self.assertEqual(ledger_data2['system_state']['core_heat'], HEAT_PER_SEQUENCE)

    def test_thermal_dissipation_over_time(self):
        """
        Verify that core heat cools down deterministically over time according to DISSIPATION_RATE_PER_SEC.
        """
        t0 = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        current_time = [t0]

        class MockDatetimeModule:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return current_time[0]
                @classmethod
                def fromisoformat(cls, date_string):
                    return datetime.datetime.fromisoformat(date_string)

        # Process 3 sequences -> 3 * 2.0 = 6.0 heat
        sequences = ["VOL101", "VOL102", "VOL103"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 6.0)

        # Advance time by 4 seconds. Dissipation = 4 * 0.5 = 2.0 heat units.
        # Expected remaining heat before new item = 6.0 - 2.0 = 4.0.
        # Adding 1 new sequence adds 2.0 -> final heat = 6.0.
        current_time[0] = t0 + datetime.timedelta(seconds=4)

        with open(self.input_file, 'w') as f:
            f.write("VOL104\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 6.0)

        # Advance time by 20 seconds (10.0 units dissipated, clamped to 0.0).
        current_time[0] = current_time[0] + datetime.timedelta(seconds=20)
        with open(self.input_file, 'w') as f:
            f.write("VOL105\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        # 0.0 + 2.0 = 2.0
        self.assertEqual(data['system_state']['core_heat'], 2.0)

    def test_thermal_lockout_and_no_silent_drains(self):
        """
        Verify:
        1. When threshold (MAX_HEAT_THRESHOLD = 10.0) is reached, ThermalOverloadError is raised.
        2. UI message keys are present and match exact indifferent world-building tone.
        3. No silent drains: sequences processed before lockout are committed atomically,
           and in main.py watcher, toSequence.txt is NOT cleared so unparsed work is preserved.
        """
        base_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetimeModule:
            timezone = datetime.timezone
            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return base_time
                @classmethod
                def fromisoformat(cls, date_string):
                    return datetime.datetime.fromisoformat(date_string)

        # 6 sequences -> 5 will reach 10.0, 6th will be refused.
        sequences = [f"VOL{100 + i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        # Check UI message keys
        self.assertEqual(err.consequence_applied, MSG_CONSEQUENCE_APPLIED)
        self.assertEqual(err.refusal_reason, MSG_REFUSAL_REASON)
        self.assertEqual(err.next_action_hint, MSG_NEXT_ACTION_HINT)
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Invariant: Partial progress before lockout must be committed to output and ledger
        with open(self.json_output, 'r') as f:
            output_data = json.load(f)
        self.assertEqual(len(output_data), 5, "First 5 sequences should have been committed atomically")

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(len(ledger_data['ledger']), 5)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)
        self.assertNotIn("VOL105", ledger_data['ledger'])

        # Invariant: Watcher / main.py must NOT silently clear toSequence.txt on ThermalOverloadError
        import main
        with patch.object(main, '__file__', os.path.join(self.project_root, 'main.py')):
            with patch.object(main, 'run_batch', side_effect=err):
                with patch.object(main, 'clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()
                    mock_clear.assert_not_called()

        # The input file still has unparsed contents (no silent drain)
        with open(self.input_file, 'r') as f:
            content = f.read()
            self.assertIn("VOL105", content)

if __name__ == '__main__':
    unittest.main()

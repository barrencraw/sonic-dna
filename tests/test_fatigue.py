import os
import sys
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, ThermalOverloadError, HEAT_PER_SEQUENCE, MAX_HEAT_THRESHOLD

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

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        """Verify core heat increases by +2.0 for each newly processed sequence."""
        sequences = ["VOL08900750712", "VOL00000000000", "VOL01002003004"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn("system_state", ledger)
        # 3 * 2.0 = 6.0 heat
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 6.0)

    def test_thermal_lockout_refusal(self):
        """Verify lockout occurs when heat reaches safety threshold (10.0)."""
        sequences = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.message_key, "Thermal Lockout")
        self.assertEqual(err.consequence_key, "Heat Accumulation")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_idempotency_no_extra_heat(self):
        """Deduplicated inputs must NOT accumulate core heat."""
        sequence = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        initial_heat = ledger["system_state"]["core_heat"]
        self.assertAlmostEqual(initial_heat, 2.0)

        # Run again with same sequence
        with open(self.input_file, 'w') as f:
            f.write(sequence + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        second_heat = ledger["system_state"]["core_heat"]
        self.assertAlmostEqual(second_heat, 2.0, msg="Heat must not increase on deduplicated input")

    def test_passive_cooling_dissipation(self):
        """Verify thermal heat dissipates over time (0.5 heat / sec)."""
        sequences = ["VOL08900750712", "VOL00000000000", "VOL01002003004"] # 6.0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        base_time = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime:
            timezone = datetime.timezone

            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return base_time

                @classmethod
                def strptime(cls, date_string, format_string):
                    return datetime.datetime.strptime(date_string, format_string)

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 6.0)

        # Fast forward time by 4 seconds (4s * 0.5/s = 2.0 dissipation -> heat should become 4.0 before new sequence)
        future_time = base_time + datetime.timedelta(seconds=4)

        class MockFutureDatetime:
            timezone = datetime.timezone

            class datetime:
                @classmethod
                def now(cls, tz=None):
                    return future_time

                @classmethod
                def strptime(cls, date_string, format_string):
                    return datetime.datetime.strptime(date_string, format_string)

        new_seq = "VOL01102203304"
        with open(self.input_file, 'w') as f:
            f.write(new_seq + "\n")

        with patch('utils.dna_ui.datetime', MockFutureDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # 6.0 - 2.0 dissipated + 2.0 new sequence = 6.0 core heat
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 6.0)

    def test_no_silent_drains_on_lockout(self):
        """When lockout occurs, input file must NOT be cleared by watcher logic in main.py."""
        # Pre-set ledger heat to 15.0 so even after fractional second dissipation it remains >= 10.0
        future_timestamp = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_state": {
                    "core_heat": 15.0,
                    "last_processed_timestamp": future_timestamp
                }
            }, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        fake_main_file = os.path.join(self.project_root, 'main.py')
        with patch.object(main, '__file__', fake_main_file):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):
                    main.process_once()
                mock_clear.assert_not_called()

        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), "VOL08900750712")

if __name__ == '__main__':
    unittest.main()

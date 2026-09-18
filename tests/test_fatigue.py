import os
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch, MagicMock

import main
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC,
    MAX_HEAT,
    UI_MESSAGE_KEYS
)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock Volume rule
        rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(rule_file, 'w') as f:
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

    def test_message_keys(self):
        """Verify UI message keys conform to required spec."""
        self.assertEqual(UI_MESSAGE_KEYS["consequence_applied"], "Heat Accumulation")
        self.assertEqual(UI_MESSAGE_KEYS["refusal_reason"], "Thermal Lockout")
        self.assertEqual(
            UI_MESSAGE_KEYS["next_action_hint"],
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

    def test_heat_accumulation_and_cooling(self):
        """Verify heat accumulates per sequence and dissipates over time."""
        # Write 2 DNA sequences (2 * 2.0 = 4.0 heat)
        with open(self.input_file, 'w') as f:
            f.write("VOL100\nVOL200\n")

        t0 = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        system_state = data['system_state']
        self.assertEqual(system_state['core_heat'], 4.0)

        # Process a 3rd sequence 4 seconds later (cools by 4 * 0.5 = 2.0 heat, then adds 2.0 = 4.0)
        t1 = t0 + datetime.timedelta(seconds=4)

        class MockDatetime2(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t1

        with open(self.input_file, 'w') as f:
            f.write("VOL300\n")

        with patch('utils.dna_ui.datetime.datetime', MockDatetime2):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data2 = json.load(f)

        self.assertEqual(data2['system_state']['core_heat'], 4.0)

    def test_thermal_lockout_refusal(self):
        """Verify processing is refused when core heat reaches/exceeds MAX_HEAT (10.0)."""
        # 5 sequences = 5 * 2.0 = 10.0 heat -> 5th sequence will trigger overload
        with open(self.input_file, 'w') as f:
            f.write("VOL100\nVOL200\nVOL300\nVOL400\nVOL500\n")

        t0 = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        self.assertIn("Thermal Lockout", str(ctx.exception))
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(ctx.exception))

        # First 4 sequences were recorded (8.0 heat)
        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        self.assertEqual(data['system_state']['core_heat'], 8.0)
        self.assertIn("VOL100", data)
        self.assertIn("VOL400", data)
        self.assertNotIn("VOL500", data)

    def test_idempotency_does_not_accumulate_heat(self):
        """Verify re-submitting duplicate sequences skips parsing and produces 0 heat."""
        dna = "VOL100"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        t0 = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)
        self.assertEqual(data['system_state']['core_heat'], 2.0)

        # Second run with same DNA
        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data2 = json.load(f)
        # Heat should remain 2.0 (no extra heat for deduplicated sequence)
        self.assertEqual(data2['system_state']['core_heat'], 2.0)

    def test_no_silent_drains_on_thermal_overload(self):
        """Verify input file toSequence.txt is NOT cleared when thermal lockout occurs."""
        with open(self.input_file, 'w') as f:
            f.write("VOL100\nVOL200\nVOL300\nVOL400\nVOL500\n")

        t0 = datetime.datetime(2025, 6, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return t0

        with patch('utils.dna_ui.datetime.datetime', MockDatetime):
            with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()

                    mock_clear.assert_not_called()

        # Input file remains on disk with unparsed sequences
        with open(self.input_file, 'r') as f:
            content = f.read()
        self.assertIn("VOL500", content)

if __name__ == '__main__':
    unittest.main()

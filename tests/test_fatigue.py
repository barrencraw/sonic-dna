import sys
from unittest.mock import MagicMock

# Mock dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import datetime
from unittest.mock import patch
from utils.dna_ui import run_batch, ThermalOverloadError

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

        # Mock rule file for Volume
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

    def test_heat_accumulation_and_lockout_keys(self):
        # 5 items = 5 * 2.0 = 10.0 heat. 6th item will hit core_heat >= 10.0 lockout
        sequences = [f"VOL00{i}" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")
        self.assertIn("Thermal Lockout", str(err))
        self.assertIn("Heat Accumulation", str(err))
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(err))

        # Check ledger state persisted heat
        with open(self.ledger_file, 'r') as f:
            state = json.load(f)
        self.assertGreaterEqual(state['system_state']['core_heat'], 10.0)

    def test_idempotency_no_heat_addition(self):
        # 1 sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL001\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_state']['core_heat']
        self.assertEqual(heat1, 2.0)

        # Run same sequence again (deduplicated)
        with open(self.input_file, 'w') as f:
            f.write("VOL001\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_state']['core_heat']
        # Core heat should not increase above 2.0 because deduplicated sequences do not add +2.0 core heat
        self.assertLessEqual(heat2, 2.0)

    def test_passive_cooling(self):
        # Simulate initial state with 8.0 heat, 20 seconds ago
        past_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=20)
        past_str = past_time.strftime('%Y-%m-%dT%H:%M:%SZ')
        with open(self.ledger_file, 'w') as f:
            json.dump({
                'ledger': {},
                'system_state': {
                    'core_heat': 8.0,
                    'last_processed_timestamp': past_str
                }
            }, f)

        # Process 1 sequence: 8.0 - (20 * 0.5) = 0.0 dissipated heat. Then 0.0 + 2.0 = 2.0 heat.
        with open(self.input_file, 'w') as f:
            f.write("VOL001\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_state']['core_heat'], 2.0)

    def test_no_silent_drains_on_lockout(self):
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        sequences = [f"VOL00{i}" for i in range(1, 7)]
        input_content = "\n".join(sequences) + "\n"
        with open(self.input_file, 'w') as f:
            f.write(input_content)

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Check input file was NOT cleared (no silent drain!)
        with open(self.input_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, input_content)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock

# Mock GUI dependencies if needed
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
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from utils.dna_ui import run_batch, ThermalOverloadError, UI_MESSAGES, DNAStatus

class TestFatigueSystem(unittest.TestCase):
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

        # Mock Volume rule
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

    def test_heat_accumulation_and_lockout(self):
        # 5 valid sequences -> 5 * 2.0 = 10.0 heat -> triggers ThermalOverloadError
        sequences = [f"VOL00{i}" for i in range(1, 6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.refusal_reason, UI_MESSAGES["REFUSAL_REASON"])
        self.assertEqual(err.consequence, UI_MESSAGES["CONSEQUENCE_APPLIED"])
        self.assertEqual(err.next_action_hint, UI_MESSAGES["NEXT_ACTION_HINT"])

        # Check that core heat is persisted at threshold in ledger
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

    def test_idempotency_no_extra_heat(self):
        # Process 2 sequences (+4.0 heat)
        with open(self.input_file, 'w') as f:
            f.write("VOL001\nVOL002\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 4.0, delta=0.5)

        # Run again with same sequences (deduplication hit)
        with open(self.input_file, 'w') as f:
            f.write("VOL001\nVOL002\n")

        run_batch()

        # Core heat should remain ~4.0 (no +2.0 per deduplicated sequence added)
        with open(self.ledger_file, 'r') as f:
            ledger_data = json.load(f)
        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 4.0, delta=0.5)

    def test_no_silent_drains_on_lockout(self):
        # Attempt to process 6 sequences (exceeds threshold of 10.0)
        sequences = [f"VOL00{i}" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Check input file was NOT cleared (no silent drain)
        with open(self.input_file, 'r') as f:
            content = f.read().strip().split('\n')
        self.assertEqual(len(content), 6)

    def test_thermal_dissipation(self):
        # Add initial heat to ledger (8.0 heat, timestamp 20 seconds ago)
        past_time = datetime.now(timezone.utc) - timedelta(seconds=20)
        past_time_str = past_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        ledger_data = {
            "ledger": {},
            "system_state": {
                "core_heat": 8.0,
                "last_processed_timestamp": past_time_str
            }
        }
        with open(self.ledger_file, 'w') as f:
            json.dump(ledger_data, f)

        # Process 1 sequence (+2.0 heat) after 20 sec cooling (20s * 0.5 = 10.0 heat dissipated -> heat drops to 0.0 + 2.0 = 2.0)
        with open(self.input_file, 'w') as f:
            f.write("VOL001\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            updated_ledger = json.load(f)
        self.assertAlmostEqual(updated_ledger['system_state']['core_heat'], 2.0, delta=0.5)

if __name__ == '__main__':
    unittest.main()

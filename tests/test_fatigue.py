import sys
from unittest.mock import MagicMock

# Mock GUI dependencies before any imports
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
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Create temporary project workspace
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

        # Mock Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
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
        """
        Processing 5 new sequences (2.0 heat units each) hits 10.0 heat capacity,
        raising ThermalOverloadError with exact UI message keys.
        """
        sequences = ["V100", "V101", "V102", "V103", "V104"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Confirm thermal state was saved in ledger
        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertGreaterEqual(ledger_data['system_state']['core_heat'], 10.0)

    def test_idempotency_zero_heat(self):
        """
        Re-processing already-processed sequences (deduplication hit) generates 0 heat.
        """
        # Process 2 items (adds 4.0 heat)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV101\n")

        run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        initial_heat = ledger_data['system_state']['core_heat']
        self.assertEqual(initial_heat, 4.0)

        # Re-run same batch immediately
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV101\n")

        run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data_after = json.load(f)

        # Core heat should not increase for deduplicated items
        self.assertAlmostEqual(ledger_data_after['system_state']['core_heat'], 4.0, delta=0.5)

    def test_passive_thermal_decay(self):
        """
        Core heat dissipates over time (0.5 heat units per second).
        """
        # Process 4 items -> accumulates 8.0 heat
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("V100\nV101\nV102\nV103\n")

        now = time.time()
        with patch('time.time', return_value=now):
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

        # Simulate 10 seconds passing (dissipates 5.0 heat -> 3.0 heat remaining)
        future_time = now + 10.0
        with patch('time.time', return_value=future_time):
            # Process 1 new item (adds 2.0 heat -> net heat should be 3.0 + 2.0 = 5.0)
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write("V104\n")
            run_batch()

        with open(self.ledger_file, 'r', encoding='utf-8') as f:
            ledger_data = json.load(f)

        self.assertAlmostEqual(ledger_data['system_state']['core_heat'], 5.0, delta=0.1)

    def test_no_silent_drain_on_lockout(self):
        """
        When process_once / watcher encounters ThermalOverloadError, input file is NOT cleared.
        """
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Put 5 items to trigger lockout
        sequences = ["V100", "V101", "V102", "V103", "V104"]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):
                    main.process_once()

                mock_clear.assert_not_called()

        # Input file remains intact so no sequences are silently dropped
        with open(self.input_file, 'r', encoding='utf-8') as f:
            lines = [l.strip() for l in f if l.strip()]
        self.assertEqual(len(lines), 5)

if __name__ == '__main__':
    unittest.main()

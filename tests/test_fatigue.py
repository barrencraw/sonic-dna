import unittest
import os
import shutil
import tempfile
import json
import time
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MAX_HEAT,
    HEAT_PER_SEQ,
    COOLING_RATE,
    load_ledger
)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary project structure
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
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

    def test_heat_accumulation(self):
        """Verify that heat increases per sequence processed."""
        # 3 sequences -> should add 3 * HEAT_PER_SEQ heat
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        expected_heat = 3 * HEAT_PER_SEQ
        self.assertAlmostEqual(state['system_heat'], expected_heat)

    def test_thermal_lockout(self):
        """Verify that processing stops and raises ThermalOverloadError when MAX_HEAT is exceeded."""
        # Calculate how many sequences to exceed MAX_HEAT
        count = int(MAX_HEAT // HEAT_PER_SEQ) + 1
        dnas = [f"V{i:03d}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        state = load_ledger(self.ledger_path)
        # Should have processed sequences up to the limit
        processed_count = len(state['ledger'])
        self.assertLess(processed_count, count)
        self.assertTrue(state['system_heat'] <= MAX_HEAT)

    def test_heat_dissipation(self):
        """Verify that heat dissipates over time."""
        # 1. Add some heat
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        state1 = load_ledger(self.ledger_path)
        heat1 = state1['system_heat']
        self.assertEqual(heat1, HEAT_PER_SEQ)
        last_time_str = state1['last_processed_timestamp']

        # 2. Wait and run again (with new DNA)
        # We'll mock the time to simulate a wait
        last_time = datetime.datetime.fromisoformat(last_time_str)
        future_time = last_time + datetime.timedelta(seconds=5)

        with open(self.input_file, 'w') as f:
            f.write("V200\n")

        # Instead of patching datetime.datetime (which leads to recursion),
        # we'll patch time.time if we used it, but we used datetime.datetime.now(timezone.utc)
        # Let's try patching datetime.datetime.now specifically.

        real_datetime = datetime.datetime
        class MockDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return future_time

        with patch('datetime.datetime', MockDatetime):
            run_batch()

        state2 = load_ledger(self.ledger_path)
        # Expected: heat1 - (5 * COOLING_RATE) + HEAT_PER_SEQ
        expected_heat = max(0.0, heat1 - (5 * COOLING_RATE)) + HEAT_PER_SEQ
        self.assertAlmostEqual(state2['system_heat'], expected_heat)

    def test_no_silent_drains_on_lockout(self):
        """Verify that on lockout, processed items are saved but the input file is NOT cleared by main.py."""
        # This tests main.py's integration with the new error
        import sys
        # Need to mock complex dependencies for main
        mock_pyside6 = MagicMock()
        sys.modules["PySide6"] = mock_pyside6
        sys.modules["PySide6.QtWidgets"] = mock_pyside6
        sys.modules["PySide6.QtCore"] = mock_pyside6
        sys.modules["PySide6.QtGui"] = mock_pyside6
        sys.modules["torch"] = MagicMock()
        sys.modules["torchaudio"] = MagicMock()
        sys.modules["sounddevice"] = MagicMock()
        sys.modules["utils.providers"] = MagicMock()

        # We need to re-import main because it might have been imported before mocks
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Setup too many items
        count = int(MAX_HEAT // HEAT_PER_SEQ) + 2
        dnas = [f"V{i:03d}" for i in range(count)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        # Mock the run_batch in main to ensure it uses our test paths
        # We must also mock os.path.abspath(__file__) in main to point to our test_dir
        with patch('main.run_batch', side_effect=run_batch):
            with patch('main.__file__', os.path.join(self.test_dir, 'main.py')):
                # In process_once, script_dir = os.path.dirname(os.path.abspath(__file__))
                # then raw_folder = os.path.join(script_dir, 'data', 'raw')
                # this should now point to self.raw_dir
                with self.assertRaises(SystemExit) as cm:
                    main.process_once()

                self.assertEqual(cm.exception.code, 1)

        # Verify input file still has content (not cleared)
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
            self.assertTrue(len(content) > 0)

        # Verify some items WERE processed in the ledger
        state = load_ledger(self.ledger_path)
        self.assertTrue(len(state['ledger']) > 0)
        self.assertLess(len(state['ledger']), count)

if __name__ == '__main__':
    unittest.main()

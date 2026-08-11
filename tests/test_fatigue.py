import sys
from unittest.mock import MagicMock

# Mock GUI / system dependencies
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

from utils.dna_ui import run_batch, ThermalOverloadError, DNAProcessingError

class MockDatetimeModule:
    timezone = datetime.timezone

    class datetime:
        _now_val = None

        @classmethod
        def now(cls, tz=None):
            return cls._now_val

        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

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
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a rule file for Volume 'V'
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Initialize mock datetime
        self.mock_datetime = MockDatetimeModule()
        self.mock_datetime.datetime._now_val = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)

        # Apply mock datetime patch specifically to utils.dna_ui
        self.patcher = patch('utils.dna_ui.datetime', self.mock_datetime)
        self.patcher.start()

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        self.patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def set_mock_time(self, dt):
        self.mock_datetime.datetime._now_val = dt

    def test_deterministic_heat_accumulation(self):
        """Verify each successfully parsed sequence adds exactly 2.0 heat units."""
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Initial run
        run_batch()

        # Check ledger
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)

        self.assertIn('V100', ledger)
        self.assertEqual(ledger['V100']['terminal_outcome'], 'success')

        state = ledger['__system_state__']
        self.assertEqual(state['core_heat'], 2.0)

    def test_heat_accumulation_sequential(self):
        """Verify sequential successful parses accumulate heat and respect time-based decay."""
        t0 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        self.set_mock_time(t0)

        # 1. Parse V100 (Heat should go 0 -> 2.0)
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['__system_state__']['core_heat'], 2.0)

        # 2. Advance time by 2 seconds (decay of 2 * 0.5 = 1.0 heat)
        # Parse V200 (Heat: 2.0 - 1.0 + 2.0 = 3.0)
        self.set_mock_time(t0 + datetime.timedelta(seconds=2))
        with open(self.input_file, 'w') as f:
            f.write("V200\n")
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['__system_state__']['core_heat'], 3.0)

    def test_lockout_threshold_and_refusal(self):
        """Verify that when heat is >= 10.0, the core is locked out and subsequent parses are refused."""
        t0 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        self.set_mock_time(t0)

        # Write 5 valid sequences in one batch.
        # Starting heat = 0.0.
        # Sequentially:
        # V100 -> success, heat becomes 2.0
        # V200 -> success, heat becomes 4.0
        # V300 -> success, heat becomes 6.0
        # V400 -> success, heat becomes 8.0
        # V500 -> success, heat becomes 10.0
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\nV400\nV500\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger['__system_state__']['core_heat'], 10.0)

        # Now, try to process a 6th sequence V600 at the same timestamp (heat is exactly 10.0)
        with open(self.input_file, 'w') as f:
            f.write("V600\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        # Check standard error messages
        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("Heat Accumulation", str(context.exception))
        self.assertIn("The system is indifferent to your deadlines.", str(context.exception))

        # Ledger should reflect V600 is "refused"
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['V600']['terminal_outcome'], 'refused')

    def test_idempotency_avoids_lockout_and_heat_accumulation(self):
        """Verify that pre-existing parsed sequences do not accumulate heat."""
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # 1st run: V100 parsed, heat is 2.0
        run_batch()

        # 2nd run: V100 is skipped, heat should remain 2.0 (minus any time decay if we don't advance time)
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['__system_state__']['core_heat'], 2.0)

    def test_no_silent_drains_input_retention(self):
        """Verify that when run_batch fails with ThermalOverloadError, main.py behaves correctly and does not clear the input file."""
        # Setup lockout
        t0 = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)
        self.set_mock_time(t0)

        # 1. Reach 10.0 heat
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\nV400\nV500\n")
        run_batch()

        # 2. Add V600 to input
        with open(self.input_file, 'w') as f:
            f.write("V600\n")

        # Mock the batch run failure inside main.py context
        if 'main' in sys.modules:
            del sys.modules['main']
        import main
        main.__file__ = os.path.join(self.test_dir, 'main.py')

        # Run main.process_once() and expect sys.exit(1) due to ThermalOverloadError
        with patch('main.clear_input_file') as mock_clear:
            with self.assertRaises(SystemExit) as exit_ctx:
                main.process_once()

            # Verify exit code is 1 (failure)
            self.assertEqual(exit_ctx.exception.code, 1)
            # Verify input file was NOT cleared
            mock_clear.assert_not_called()

        # Verify the file still contains the refused string
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
        self.assertEqual(content, "V600")

if __name__ == '__main__':
    unittest.main()

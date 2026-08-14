import os
import sys
import shutil
import unittest
import json
import tempfile
import datetime as real_datetime
from unittest.mock import patch, MagicMock

# Mock imports before loading utils.dna_ui
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import run_batch, ThermalOverloadError, PersistenceError

class MockDatetimeModule:
    timezone = real_datetime.timezone

    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MockDatetimeModule._now

        @classmethod
        def strptime(cls, date_string, format_string):
            return real_datetime.datetime.strptime(date_string, format_string)

    _now = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

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

        # Mock standard Volume rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 99, "pad": 2},
                    "curve": {"description": "curve shape", "min": 0, "max": 9, "pad": 1}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Reset Mock Datetime to initial state
        MockDatetimeModule._now = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        # Patch datetime module
        self.datetime_patcher = patch('utils.dna_ui.datetime', new=MockDatetimeModule)
        self.datetime_patcher.start()

    def tearDown(self):
        self.datetime_patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_on_successful_parsing(self):
        """Test that successfully parsed sequences increase core heat by 2.0 units each."""
        # Write 2 valid sequences (prefixes must be 'VOL')
        with open(self.input_file, 'w') as f:
            f.write("VOL001000\nVOL002000\n")

        run_batch()

        # Check ledger state
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn("system_state", ledger_data)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 4.0)

    def test_heat_dissipation_over_time(self):
        """Test that elapsed time cools the system down at a rate of 0.5 units/sec."""
        # Step 1: Accumulate some heat (2 sequences -> 4.0 heat)
        with open(self.input_file, 'w') as f:
            f.write("VOL001000\nVOL002000\n")
        run_batch()

        # Step 2: Advance time by 4 seconds (should cool down by 4 * 0.5 = 2.0 units)
        MockDatetimeModule._now += real_datetime.timedelta(seconds=4)

        # Process a third sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL003000\n")
        run_batch()

        # Core heat should be: 4.0 (initial) - 2.0 (dissipated) + 2.0 (new sequence) = 4.0
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 4.0)

    def test_thermal_lockout_error(self):
        """Test that safety threshold (10.0 core heat) triggers a ThermalOverloadError and refuses sequences."""
        # 6 sequences will generate 6 * 2.0 = 12.0 heat units, which exceeds 10.0 lockout threshold.
        # Sequence 1-5 should process successfully (reaching 10.0 heat).
        # Sequence 6 should be refused, and a ThermalOverloadError raised.
        sequences = [
            "VOL001000",
            "VOL002000",
            "VOL003000",
            "VOL004000",
            "VOL005000",
            "VOL006000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        # Verify refusal error details
        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("Wait for dissipation", str(context.exception))

        # Check ledger and outputs
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # The first 5 sequences must be committed as 'success' in the ledger
        for seq in sequences[:5]:
            self.assertEqual(ledger_data["ledger"][seq]["terminal_outcome"], "success")

        # The 6th sequence should NOT be processed or skipped (since it broke before parsing)
        self.assertNotIn(sequences[5], ledger_data["ledger"])

        # Core heat should be 10.0 (reached at sequence 5, sequence 6 was refused)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 10.0)

    def test_no_silent_drains_on_overload_failure(self):
        """Test main.py's watch_loop logic: if run_batch raises ThermalOverloadError, toSequence.txt is NOT cleared."""
        # Force import main after mock setup
        if 'main' in sys.modules:
            del sys.modules['main']
        import main
        main.__file__ = os.path.join(self.test_dir, 'main.py')

        # Write 6 sequences to cause an overload
        sequences = [
            "VOL001000",
            "VOL002000",
            "VOL003000",
            "VOL004000",
            "VOL005000",
            "VOL006000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        # Running process_once() should exit with status code 1 when ThermalOverloadError is raised,
        # and the input file should NOT have been cleared/truncated.
        with self.assertRaises(SystemExit) as cm:
            main.process_once()

        self.assertEqual(cm.exception.code, 1)

        # Verify file still has contents and was not cleared
        with open(self.input_file, 'r') as f:
            content = f.read().strip()
            self.assertTrue(len(content) > 0)
            self.assertEqual(content.splitlines(), sequences)

    def test_idempotency_applied_exactly_once(self):
        """Test that duplicate runs do not add extra heat or duplicate side-effects."""
        # First successful run with a sequence
        with open(self.input_file, 'w') as f:
            f.write("VOL001000\n")
        run_batch()

        # Check ledger and heat
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)

        # Now, second run with the exact same sequence (should hit idempotency)
        with open(self.input_file, 'w') as f:
            f.write("VOL001000\n")
        run_batch()

        # Check ledger and heat - heat must still be 2.0 (or cooled down slightly if time progressed,
        # but time did not progress, so it must not have increased by another 2.0)
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data["system_state"]["core_heat"], 2.0)

if __name__ == '__main__':
    unittest.main()

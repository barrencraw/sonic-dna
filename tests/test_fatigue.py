import sys
from unittest.mock import MagicMock

# Mock dependencies before any imports
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
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger, save_ledger

class MockDatetime:
    timezone = datetime.timezone
    class datetime:
        _now = datetime.datetime.now(datetime.timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls._now
        @classmethod
        def strptime(cls, date_string, format_string):
            return datetime.datetime.strptime(date_string, format_string)

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
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock Volume rule file
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

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        """Verify that successfully parsed and error DNA strings accumulate heat, and exceed threshold lockout."""
        # 1. Successful parse adds 2.0 heat units
        with open(self.input_file, 'w') as f:
            f.write("VOL100\n")

        MockDatetime.datetime._now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        run_batch()

        # Check ledger and heat
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 2.0)

        # 2. Add an invalid DNA sequence (error) which adds 1.0 heat units
        with open(self.input_file, 'w') as f:
            f.write("INVALID_DNA_STRING\n")

        MockDatetime.datetime._now = datetime.datetime(2026, 3, 2, 12, 0, 10, tzinfo=datetime.timezone.utc) # 10s later (should cool down 5.0 heat, but max of 0.0)
        # 10s elapsed: 10 * 0.5 = 5.0 dissipation.
        # Heat was 2.0, so 2.0 - 5.0 -> cools to 0.0.
        # Then we process invalid DNA (adds 1.0 heat) -> total should be 1.0.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], 1.0)

        # 3. Accumulate up to lockout threshold (10.0)
        # We need 9.0 more heat. Let's write 5 more valid sequences.
        # Each adds 2.0 heat. 5 * 2.0 = 10.0 heat. Total heat becomes 1.0 + 10.0 = 11.0.
        # Wait, inside the loop, after 5th sequence is parsed, heat becomes 11.0.
        # But wait! If we run them in a batch, heat accumulates sequence by sequence.
        # 1.0 + 2.0 -> 3.0 (seq 1)
        # 3.0 + 2.0 -> 5.0 (seq 2)
        # 5.0 + 2.0 -> 7.0 (seq 3)
        # 7.0 + 2.0 -> 9.0 (seq 4)
        # 9.0 + 2.0 -> 11.0 (seq 5)
        # Each is checked before processing. For Seq 5, current heat is 9.0 < 10.0. So it is processed successfully.
        # After Seq 5, heat becomes 11.0.
        # If we have a 6th sequence, when it checks, current_heat is 11.0 >= 10.0, so it raises ThermalOverloadError!
        with open(self.input_file, 'w') as f:
            f.write("VOL101\nVOL102\nVOL103\nVOL104\nVOL105\nVOL106\n")

        # Mock time to be same (no cooling)
        MockDatetime.datetime._now = datetime.datetime(2026, 3, 2, 12, 0, 10, tzinfo=datetime.timezone.utc)

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check ledger of the failed run. The first 5 sequences must be saved, but the 6th is refused.
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # Heat was 1.0. Seq 1-5 processed, adding 10.0 heat -> 11.0.
        # Seq 6 was refused, so it did not get processed.
        self.assertEqual(ledger_data['system_state']['core_heat'], 11.0)
        self.assertIn("VOL105", ledger_data['ledger'])
        self.assertNotIn("VOL106", ledger_data['ledger'])

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_passive_cooling_dissipation(self):
        """Verify that passive core cooling cools down the system over time."""
        # Setup initial heat to 8.0
        ledger_data = {
            "ledger": {},
            "system_state": {
                "core_heat": 8.0,
                "last_processed_timestamp": "2026-03-02T12:00:00Z"
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger_data, f)

        # 6 seconds later. Cooling rate is 0.5 heat/sec.
        # Dissipated: 6 * 0.5 = 3.0 heat. Heat should become 8.0 - 3.0 = 5.0.
        MockDatetime.datetime._now = datetime.datetime(2026, 3, 2, 12, 0, 6, tzinfo=datetime.timezone.utc)

        # Run with no new items to trigger passive cooling save
        with open(self.input_file, 'w') as f:
            f.write("") # empty

        run_batch()

        with open(self.ledger_path, 'r') as f:
            updated = json.load(f)
        self.assertEqual(updated['system_state']['core_heat'], 5.0)

    def test_no_silent_drains(self):
        """Verify that if run_batch raises ThermalOverloadError, the main runner does NOT clear input file."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with open(self.input_file, 'w') as f:
            f.write("VOL101\n")

        # Mock run_batch to raise ThermalOverloadError
        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('main.run_batch', side_effect=ThermalOverloadError("Locked Out")):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()
                    mock_clear.assert_not_called()

        # Input file should still have the unparsed sequences
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), "VOL101")

if __name__ == '__main__':
    unittest.main()

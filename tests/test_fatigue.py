import os
import json
import shutil
import unittest
import datetime
import tempfile
from unittest.mock import patch

from utils.dna_ui import main as run_batch, ThermalOverloadError, DNAProcessingError, load_ledger, save_ledger

# Define a mock now time that we can control
MOCK_NOW_TIME = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

class MockDatetime:
    timezone = datetime.timezone
    class datetime:
        @classmethod
        def now(cls, tz=None):
            return MOCK_NOW_TIME
        @classmethod
        def fromisoformat(cls, s):
            return datetime.datetime.fromisoformat(s)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        global MOCK_NOW_TIME
        MOCK_NOW_TIME = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # Create temporary project directories
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

        # Mock a valid rule file for testing
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Set up a base clean ledger file
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_and_lockout(self):
        """Verify heat accumulation per sequence and transition to lockout state."""
        # Write 8 distinct sequences (each adds 15.0 heat, 7 * 15.0 = 105.0)
        sequences = [f"V{100 + i:03d}" for i in range(8)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        # Run batch. It should process up to 7 items (0 to 6), setting heat to 105.0.
        # The 8th item (index 7) should trigger a ThermalLockout and raise ThermalOverloadError.
        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        self.assertIn("Thermal Lockout", str(ctx.exception))

        # Check ledger
        ledger = load_ledger(self.ledger_path)
        self.assertIn("system_heat", ledger)
        self.assertGreaterEqual(ledger["system_heat"], 100.0)

        # Processed items should be 7
        processed_ledger_data = ledger["ledger"]
        self.assertEqual(len(processed_ledger_data), 7)
        for i in range(7):
            self.assertIn(sequences[i], processed_ledger_data)
        self.assertNotIn(sequences[7], processed_ledger_data)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_dissipation_over_time(self):
        """Verify heat dissipation over elapsed time."""
        global MOCK_NOW_TIME

        # Process 3 items → should accumulate 45.0 heat
        sequences = [f"V{100 + i:03d}" for i in range(3)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 45.0)

        # Advance time by 20 seconds
        MOCK_NOW_TIME += datetime.timedelta(seconds=20)

        # Process 1 more sequence
        with open(self.input_file, 'w') as f:
            f.write("V500\n")

        run_batch()

        # Heat should have dissipated by 20.0 (45.0 - 20.0 = 25.0), and then sequence adds 15.0 = 40.0
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 40.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_no_heat(self):
        """Verify skipped sequences due to idempotency do not accumulate heat."""
        # Process a sequence
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger["system_heat"], 15.0)

        # Run again with same sequence. It should be skipped and heat should remain 15.0 (no new heat added).
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger["system_heat"], 15.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_no_silent_drains(self):
        """Verify that committed items before lockout are saved, and the input file is not cleared on error."""
        # 8 items will cause lockout
        sequences = [f"V{100 + i:03d}" for i in range(8)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        # Mock main.py's watcher pattern: if run_batch raises error, do not clear
        import main
        with patch('main.__file__', os.path.join(self.test_dir, 'main.py')):
            with patch('main.clear_input_file') as mock_clear:
                with self.assertRaises(SystemExit):  # process_once exits with 1 on failure
                    main.process_once()
                mock_clear.assert_not_called()

        # The input file must not be cleared and must still have original contents
        with open(self.input_file, 'r') as f:
            content = f.read().splitlines()
        self.assertEqual(content, sequences)

        # But the 7 processed sequences should have been committed to the ledger and outputs
        ledger = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger["ledger"]), 7)

        # Output JSON should have 7 entries
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, 'r') as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 7)

if __name__ == '__main__':
    unittest.main()

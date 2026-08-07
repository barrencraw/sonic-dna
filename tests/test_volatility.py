import sys
from unittest.mock import MagicMock

# Mock dependencies before imports to protect the test environment
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
from utils.dna_ui import main as run_batch, AcousticSaturationError, load_ledger, save_ledger

class TestVolatilitySystem(unittest.TestCase):
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
        self.ledger_path = os.path.join(self.test_dir, 'data', 'processed_ledger.json')

        # Mock a rule file (Volume prefix V)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        # Set cwd to test_dir so run_batch operates in our sandbox
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('time.time', return_value=1718000000.0)
    def test_volatility_accumulation_and_stabilize(self, mock_time):
        """Test that normal and HF sequences accumulate volatility, and STABILIZE reduces it."""
        # Write normal and HF sequences
        with open(self.input_file, 'w') as f:
            f.write("V100\n"        # +1.0 -> 1.0
                    "V200_HF\n"     # +3.0 -> 4.0
                    "STABILIZE\n"   # -4.0 -> 0.0
                    "V300\n")       # +1.0 -> 1.0

        run_batch()

        # Load ledger and check metadata
        ledger = load_ledger(self.ledger_path)
        metadata = ledger.get('__metadata__', {})
        self.assertAlmostEqual(metadata.get('system_volatility', 0.0), 1.0, places=4)

        # Confirm STABILIZE got skipped and is in ledger but not in output
        self.assertEqual(ledger.get('STABILIZE', {}).get('terminal_outcome'), 'skipped')

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as jf:
            parsed = json.load(jf)

        # Parsed items should be V100, V200_HF, and V300 (no STABILIZE in JSON)
        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]['dna'], 'V100')
        self.assertEqual(parsed[1]['dna'], 'V200_HF')
        self.assertEqual(parsed[2]['dna'], 'V300')

    @patch('time.time', return_value=1718000000.0)
    def test_lockout_threshold_and_error(self, mock_time):
        """Test that reaching or exceeding 10.0 volatility triggers AcousticSaturationError."""
        # Accumulate 9.0 volatility first
        with open(self.input_file, 'w') as f:
            f.write("V100_HF\n"  # +3.0
                    "V200_HF\n"  # +3.0
                    "V300_HF\n") # +3.0 -> Total 9.0
        run_batch()

        # Check ledger has 9.0 volatility
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger.get('__metadata__', {}).get('system_volatility'), 9.0, places=4)

        # Now, try to run another sequence that would exceed or trigger threshold, or run multiple.
        # Volatility is currently 9.0.
        # Next sequence (V400) adds 1.0, raising volatility to 10.0.
        # The following sequence (V500) will check and see 10.0, triggering lockout.
        with open(self.input_file, 'w') as f:
            f.write("V400\n"   # +1.0 -> Total 10.0
                    "V500\n")  # Checked BEFORE processing -> raises AcousticSaturationError

        with self.assertRaises(AcousticSaturationError) as ctx:
            run_batch()

        self.assertIn("Acoustic Saturation Lockout", str(ctx.exception))

        # Check that V400 was processed successfully (as it was run before lockout was detected)
        # but V500 was not processed (is not in ledger).
        ledger = load_ledger(self.ledger_path)
        self.assertIn('V400', ledger)
        self.assertNotIn('V500', ledger)
        self.assertEqual(ledger['V400']['terminal_outcome'], 'success')

    @patch('time.time', return_value=1718000000.0)
    def test_idempotency_prevents_double_accumulation(self, mock_time):
        """Test that running the same sequence twice does not add volatility a second time."""
        # 1st run
        with open(self.input_file, 'w') as f:
            f.write("V100_HF\n")
        run_batch()

        ledger = load_ledger(self.ledger_path)
        vol1 = ledger.get('__metadata__', {}).get('system_volatility', 0.0)
        self.assertAlmostEqual(vol1, 3.0, places=4)

        # 2nd run with same sequence
        with open(self.input_file, 'w') as f:
            f.write("V100_HF\n")
        run_batch()

        # Volatility should still be 3.0 (or decayed slightly, but not increased)
        ledger = load_ledger(self.ledger_path)
        vol2 = ledger.get('__metadata__', {}).get('system_volatility', 0.0)
        self.assertTrue(vol2 <= 3.0, f"Volatility should not increase on duplicate run, but got {vol2}")

    def test_time_based_dissipation(self):
        """Test that volatility decays based on real time elapsed."""
        # Add volatility
        with open(self.input_file, 'w') as f:
            f.write("V100_HF\n") # +3.0
        run_batch()

        ledger = load_ledger(self.ledger_path)
        metadata = ledger.get('__metadata__', {})
        t0 = metadata.get('last_transaction_time', 0.0)
        self.assertAlmostEqual(metadata.get('system_volatility'), 3.0, places=4)

        # Mock elapsed time of 5 seconds (decay: 5 * 0.2 = 1.0)
        t1 = t0 + 5.0
        with patch('time.time', return_value=t1):
            with open(self.input_file, 'w') as f:
                f.write("V200\n") # +1.0
            run_batch()

        # Expected volatility: 3.0 - 1.0 (decay) + 1.0 (V200) = 3.0
        ledger = load_ledger(self.ledger_path)
        vol = ledger.get('__metadata__', {}).get('system_volatility', 0.0)
        self.assertAlmostEqual(vol, 3.0, places=4)

    @patch('time.time', return_value=1718000000.0)
    def test_stabilize_bypasses_lockout(self, mock_time):
        """Test that STABILIZE works even when locked out (system_volatility >= 10.0)."""
        # Set volatility to 12.0 manually in ledger
        ledger = {
            '__metadata__': {
                'system_volatility': 12.0,
                'last_transaction_time': 1718000000.0
            }
        }
        save_ledger(self.ledger_path, ledger)

        # Try to run STABILIZE (reduces by 4.0 to 8.0) and then V100
        with open(self.input_file, 'w') as f:
            f.write("STABILIZE\n"
                    "V100\n")

        # This should execute successfully because STABILIZE executes first and brings volatility down to 8.0,
        # permitting V100 to parse (volatility becomes 9.0)
        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertIn('STABILIZE', ledger)
        self.assertIn('V100', ledger)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 9.0, places=4)

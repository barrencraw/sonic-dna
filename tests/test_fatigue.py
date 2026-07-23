import sys
import os
import json
import shutil
import tempfile
import unittest
import datetime
from unittest.mock import patch, MagicMock

# Mock dependencies before imports to avoid GUI/sounddevice errors
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import run_batch, ThermalOverloadError, DNAStatus, DNAProcessingError

class MockDatetime:
    timezone = datetime.timezone

    class datetime:
        _current_time = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._current_time

        @classmethod
        def fromisoformat(cls, val):
            return datetime.datetime.fromisoformat(val)

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

        # Force MockDatetime to start at base time
        MockDatetime.datetime._current_time = datetime.datetime(2026, 3, 2, 10, 0, 0, tzinfo=datetime.timezone.utc)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Patch datetime inside utils.dna_ui
        self.patcher = patch('utils.dna_ui.datetime', MockDatetime)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_per_sequence(self):
        """Verify that successfully parsing sequences accumulates heat in the ledger."""
        # Process 3 DNA strings (each should add 20 heat)
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # Total heat accumulated should be 3 * 20 = 60
        self.assertAlmostEqual(ledger['system_heat'], 60.0)
        self.assertFalse(ledger['lockout'])

    def test_thermal_lockout_and_refusal(self):
        """Verify that system transitions to REFUSED state and raises ThermalOverloadError when heat > 100."""
        # Process 5 sequences (each adds 20 heat). Total heat = 100 (just at limit, no lockout yet)
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\nV400\nV500\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 100.0)
        self.assertFalse(ledger['lockout'])

        # Process 1 more sequence. Total heat becomes 120, which is > 100, entering lockout.
        with open(self.input_file, 'w') as f:
            f.write("V600\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 120.0)
        self.assertTrue(ledger['lockout'])

        # Now try to process another sequence. Since lockout is True and heat > 0,
        # it should refuse processing and raise ThermalOverloadError.
        with open(self.input_file, 'w') as f:
            f.write("V700\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("Wait for dissipation", str(context.exception))

    def test_heat_dissipation_over_time(self):
        """Verify that heat dissipates at 2.0 units per second and lockout is cleared when heat <= 0."""
        # Accumulate 120 heat and enter lockout
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\nV400\nV500\nV600\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertTrue(ledger['lockout'])
        self.assertAlmostEqual(ledger['system_heat'], 120.0)

        # Advance time by 30 seconds. Dissipation = 30 * 2.0 = 60 units. Remaining heat = 120 - 60 = 60.
        MockDatetime.datetime._current_time += datetime.timedelta(seconds=30)

        # Try processing a new item; it should still be refused
        with open(self.input_file, 'w') as f:
            f.write("V700\n")
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 60.0)
        self.assertTrue(ledger['lockout'])

        # Advance time by another 30 seconds (total 60 seconds).
        # Dissipation = 60 * 2.0 = 120 units. Heat should drop to 0.0 and lockout should clear.
        MockDatetime.datetime._current_time += datetime.timedelta(seconds=30)

        with open(self.input_file, 'w') as f:
            f.write("V700\n")

        # This should succeed since lockout is cleared now
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 20.0) # 0.0 + 20.0 from V700
        self.assertFalse(ledger['lockout'])

    def test_idle_cycle_dissipation(self):
        """Verify that even with zero new sequences, heat dissipation is recorded and persisted to the ledger."""
        # Initial run to set up system heat at 40
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 40.0)

        # Advance time by 10 seconds. No input file changes.
        MockDatetime.datetime._current_time += datetime.timedelta(seconds=10)

        with open(self.input_file, 'w') as f:
            pass

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # Heat should have dissipated by 10 * 2.0 = 20 units. Remaining: 40 - 20 = 20.
        self.assertAlmostEqual(ledger['system_heat'], 20.0)

    def test_idempotency_avoids_heat_accumulation(self):
        """Verify that duplicate/already processed DNA sequences do not accumulate additional heat."""
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 20.0)

        # Try processing the same V100 again.
        with open(self.input_file, 'w') as f:
            f.write("V100\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['system_heat'], 20.0)

if __name__ == '__main__':
    unittest.main()
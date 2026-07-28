import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch, MagicMock

# Mock GUI dependencies to avoid issues
import sys
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

from utils.dna_ui import run_batch, ThermalOverloadError, DNAProcessingError

class MockDatetime:
    timezone = datetime.timezone
    class datetime:
        _now = None
        @classmethod
        def now(cls, tz=None):
            return cls._now
        @classmethod
        def fromisoformat(cls, s):
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            return datetime.datetime.fromisoformat(s)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

        # Use deterministic time
        MockDatetime.datetime._now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            if os.path.exists(self.backup_folder):
                shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_dissipation(self):
        # DNA sequences (Prefix for Volume)
        dna_list = ["VOL08900750712", "VOL00000000000"]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        # Set time to T0
        t0 = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetime.datetime._now = t0

        # 1. First run processing 2 sequences (each +20.0 heat -> 40.0 total)
        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        system_state = ledger['system_state']
        # Assert heat accumulated to 40.0
        self.assertEqual(system_state['heat'], 40.0)
        self.assertFalse(system_state['lockout'])

        # 2. Advance time by 4 seconds (cooling rate = 5.0/sec -> 20.0 cooled down)
        t1 = t0 + datetime.timedelta(seconds=4)
        MockDatetime.datetime._now = t1

        # Process a new sequence
        new_dna = "VOL11122233344"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        system_state = ledger['system_state']
        # Heat should be: 40.0 (prev) - 20.0 (cooling) + 20.0 (new_dna) = 40.0
        # Use non-strict/assertAlmostEqual to be robust
        self.assertAlmostEqual(system_state['heat'], 40.0, places=1)

    def test_transition_to_lockout(self):
        # 5 sequences → +100.0 heat total
        dna_list = [f"VOL0000000000{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        t0 = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetime.datetime._now = t0

        # Run batch. This should trigger ThermalOverloadError.
        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError) as context:
                run_batch()

            # Verify UI message keys
            err = context.exception
            self.assertEqual(err.consequence, "Heat Accumulation")
            self.assertEqual(err.reason, "Thermal Lockout")
            self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check ledger
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        system_state = ledger['system_state']
        self.assertEqual(system_state['heat'], 100.0)
        self.assertTrue(system_state['lockout'])

    def test_refusal_on_lockout_and_no_silent_drains(self):
        # Initialize ledger in lockout state
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_state": {
                    "heat": 100.0,
                    "last_processed_timestamp": "2026-03-02T12:00:00SZ",
                    "lockout": True
                },
                "ledger": {}
            }, f)

        # Try to process while in lockout (and without waiting enough time to recover)
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 1. Advance time by 2 seconds (heat cools down to 90.0, but still above recovery threshold 50.0)
        t0 = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)
        t1 = t0 + datetime.timedelta(seconds=2)
        MockDatetime.datetime._now = t1

        with patch('utils.dna_ui.datetime', MockDatetime):
            with self.assertRaises(ThermalOverloadError):
                run_batch()

        # Check that ledger is updated with new timestamp and dissipated heat, but sequence was refused (not processed)
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        system_state = ledger['system_state']
        self.assertAlmostEqual(system_state['heat'], 90.0, places=1)
        self.assertTrue(system_state['lockout'])
        self.assertNotIn(dna, ledger.get('ledger', {}))

        # 2. Advance time by another 10 seconds (total 12 seconds elapsed since T0 -> heat cools to 40.0 < 50.0 Recovery threshold)
        t2 = t0 + datetime.timedelta(seconds=12)
        MockDatetime.datetime._now = t2

        # Try to run batch again, now it should succeed because lockout cleared!
        with patch('utils.dna_ui.datetime', MockDatetime):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        system_state = ledger['system_state']
        # Heat: 100.0 - 12 * 5.0 (60.0 cooling -> 40.0) + 20.0 (dna parsed) = 60.0
        self.assertAlmostEqual(system_state['heat'], 60.0, places=1)
        self.assertFalse(system_state['lockout'])
        self.assertIn(dna, ledger.get('ledger', {}))

if __name__ == '__main__':
    unittest.main()

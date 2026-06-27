import os
import json
import shutil
import unittest
import time
from unittest.mock import MagicMock, patch
import sys

# Mock dependencies for headless testing
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

from utils.dna_ui import main as run_batch, DNAStatus

class TestThermalDebt(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 1. Process 3 DNA strings
        dnas = ["VOL08900750712", "VOL00000000000", "VOL11122233344"]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # 3 successes * 5.0 heat = 15.0 heat
        self.assertGreaterEqual(ledger_data["system_heat"], 14.9)
        self.assertLessEqual(ledger_data["system_heat"], 15.1)
        self.assertEqual(len(ledger_data["ledger"]), 3)

    def test_thermal_lockout(self):
        # 1. Pre-seed ledger with high heat
        high_heat_ledger = {
            "system_heat": 105.0,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(high_heat_ledger, f)

        # 2. Try to process new DNA
        dna = "VOL111222333"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertEqual(ledger_data["ledger"][dna]["terminal_outcome"], DNAStatus.REFUSED.value)
        # Heat should NOT have increased for a refusal
        self.assertLessEqual(ledger_data["system_heat"], 105.0)

    def test_refusal_retry_after_cooldown(self):
        # 1. Pre-seed ledger with refusal and high heat, but OLD timestamp
        dna = "VOL11122233344"
        one_hour_ago = time.time() - 3600.0
        seed_ledger = {
            "system_heat": 120.0,
            "last_processed_timestamp": one_hour_ago,
            "ledger": {
                dna: {
                    "terminal_outcome": DNAStatus.REFUSED.value,
                    "timestamp": "2026-06-27 12:00:00"
                }
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(seed_ledger, f)

        # 2. Process same DNA again. Cooldown should have happened.
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # Dissipation: 3600s * 0.5 = 1800 units. Heat should be 0 before processing.
        # Heat after processing: 0 + 5.0 = 5.0
        self.assertEqual(ledger_data["ledger"][dna]["terminal_outcome"], DNAStatus.SUCCESS.value)
        self.assertAlmostEqual(ledger_data["system_heat"], 5.0, places=1)

    def test_heat_dissipation(self):
        # 1. Pre-seed heat and set timestamp to 10 seconds ago
        initial_heat = 50.0
        ten_secs_ago = time.time() - 10.0
        seed_ledger = {
            "system_heat": initial_heat,
            "last_processed_timestamp": ten_secs_ago,
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(seed_ledger, f)

        # 2. Run batch
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # Expected dissipation: 10 seconds * 0.5 units/sec = 5.0 units
        # Heat before processing: 50.0 - 5.0 = 45.0
        # Heat after processing: 45.0 + 5.0 = 50.0
        self.assertAlmostEqual(ledger_data["system_heat"], 50.0, places=1)

    def test_idempotency_no_heat_gain(self):
        # 1. Process one item
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        heat_after_first = ledger_data["system_heat"]

        # 2. Process same item again immediately
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        # Heat should be lower (dissipation) or equal, but definitely NOT higher
        self.assertLessEqual(ledger_data["system_heat"], heat_after_first)

if __name__ == '__main__':
    unittest.main()

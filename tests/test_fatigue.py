import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, MAX_HEAT, HEAT_PER_ITEM, COOLING_RATE_PER_SEC

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 5 DNA strings
        dnas = [f"VOL{i:011d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 5.0 * HEAT_PER_ITEM)
        self.assertEqual(len(state['ledger']), 5)

    def test_thermal_overload(self):
        # 12 DNA strings, MAX_HEAT is 10.0
        dnas = [f"VOL{i:011d}" for i in range(12)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have stopped at 10 items
        self.assertAlmostEqual(state['system_heat'], 10.0)
        self.assertEqual(len(state['ledger']), 10)

        # Verify that we can't process more until we cool down
        with open(self.input_file, 'w') as f:
            f.write("VOL99999999999\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        self.assertEqual(len(state2['ledger']), 10, "Should not have processed more while at MAX_HEAT")

    def test_cooling(self):
        # Process 5 items to get heat to 5.0
        dnas = [f"VOL{i:011d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 5.0)

        # Mock time to simulate cooling
        # We'll just wait for 2 seconds (0.02 cooling)
        time.sleep(2)

        # Process 1 more item
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000006\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Expected heat: 5.0 - (elapsed * 0.01) + 1.0
        # elapsed should be ~2s
        expected_heat = 5.0 - (2 * COOLING_RATE_PER_SEC) + 1.0
        self.assertLess(state2['system_heat'], 6.0)
        self.assertGreater(state2['system_heat'], 5.0)

    def test_legacy_migration(self):
        # Create a legacy ledger
        legacy_data = {
            "VOL00000000001": {"terminal_outcome": "success", "timestamp": "2025-01-01 00:00:00"}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(legacy_data, f)

        # Run batch with a new item
        with open(self.input_file, 'w') as f:
            f.write("VOL00000000002\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertIn("system_heat", state)
        self.assertIn("ledger", state)
        self.assertEqual(len(state["ledger"]), 2)
        self.assertIn("VOL00000000001", state["ledger"])
        self.assertIn("VOL00000000002", state["ledger"])

if __name__ == '__main__':
    unittest.main()

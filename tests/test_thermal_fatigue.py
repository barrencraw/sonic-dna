import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

    def test_heat_accumulation(self):
        # VOL prefix: 0.1 base + 0.2 penalty = 0.3 per string
        dna_list = [f"VOL0000000000{i}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # 5 * 0.3 = 1.5
        self.assertAlmostEqual(state['system_heat'], 1.5, places=2)

    def test_cooling(self):
        # 1. Generate heat
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        initial_heat = state['system_heat'] # 0.3
        self.assertAlmostEqual(initial_heat, 0.3, places=2)
        last_ts = state['last_processed_timestamp']

        # 2. Simulate time passing (100 seconds)
        # COOLING_RATE = 0.0083
        # 100 * 0.0083 = 0.83 cooling
        # But we only have 0.3 heat, so it should be 0.0

        future_time = last_ts + 100
        with patch('time.time', return_value=future_time):
            # Run batch with a new DNA string (so it actually processes something and saves)
            # Actually run_batch() now always saves if system_heat changed
            with open(self.input_file, 'w') as f:
                f.write("VOL00000000001\n")
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Initial 0.3 - 100 * 0.0083 = -0.53 -> max(0, -0.53) = 0.0
        # THEN add 0.3 for the new DNA VOL00000000001
        self.assertAlmostEqual(state['system_heat'], 0.3, places=2)

    def test_thermal_refusal(self):
        # Create ledger file first so it exists even if refusal happens early
        with open(self.ledger_path, 'w') as f:
            json.dump({"system_heat": 0.0, "last_processed_timestamp": time.time(), "ledger": {}}, f)

        # MAX_HEAT = 10.0
        # VOL = 0.3 per string. Need 34 strings to exceed 10.0 (34 * 0.3 = 10.2)
        dna_list = [f"VOL{str(i).zfill(11)}" for i in range(40)]
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(d + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertIn("Hardware safety lockout", str(cm.exception))

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have stopped before exceeding 10.0
        self.assertLessEqual(state['system_heat'], 10.0)

    def test_idempotency_no_heat(self):
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 0.3 heat

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)

        # Second run with same DNA
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Heat should NOT have increased (except for minimal time difference cooling, which we can ignore or mock)
        self.assertAlmostEqual(state1['system_heat'], state2['system_heat'], places=4)

if __name__ == '__main__':
    unittest.main()

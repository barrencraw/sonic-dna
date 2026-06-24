import unittest
import os
import json
import shutil
import tempfile
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_SEQ, COOLING_RATE_PER_SEC

class TestFatigue(unittest.TestCase):
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

        # Mock a rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "amp": {"description": "amp", "min": 0, "max": 999, "pad": 3},
                    "lr": {"description": "lr", "min": 0, "max": 99, "pad": 2},
                    "sur": {"description": "sur", "min": 0, "max": 9, "pad": 1},
                    "head": {"description": "head", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        """Verify that heat increases with each new sequence."""
        dnas = ["VOL00101101", "VOL00202202"]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        expected_heat = len(dnas) * HEAT_PER_SEQ
        self.assertEqual(state['system_heat'], expected_heat)

    def test_thermal_overload_refusal(self):
        """Verify that reaching MAX_HEAT raises ThermalOverloadError."""
        # Calculate how many sequences to hit MAX_HEAT
        count = int(MAX_HEAT / HEAT_PER_SEQ) + 1
        dnas = [f"VOL{str(i).zfill(3)}01101" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be at the level of the last successful processing + one refused
        # Actually in my implementation, it raises BEFORE processing the one that would exceed.
        # So it should be <= MAX_HEAT.
        self.assertLessEqual(state['system_heat'], MAX_HEAT)

    def test_deterministic_cooling(self):
        """Verify that heat dissipates over time."""
        # 1. Generate some heat
        with open(self.input_file, 'w') as f:
            f.write("VOL00101101\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        initial_heat = state1['system_heat']
        self.assertEqual(initial_heat, HEAT_PER_SEQ)

        # 2. Wait a bit (simulate time passage in ledger)
        wait_sec = 2.0
        state1['last_processed_timestamp'] -= wait_sec
        with open(self.ledger_path, 'w') as f:
            json.dump(state1, f)

        # 3. Run again (with no new items or a different one)
        with open(self.input_file, 'w') as f:
            f.write("VOL00202202\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        expected_cooling = wait_sec * COOLING_RATE_PER_SEC
        # New heat = (initial - cooling) + HEAT_PER_SEQ
        expected_heat = (initial_heat - expected_cooling) + HEAT_PER_SEQ
        self.assertAlmostEqual(state2['system_heat'], expected_heat, places=2)

    def test_idempotency_does_not_increase_heat(self):
        """Verify that re-processing an existing key doesn't add heat."""
        dna = "VOL00101101"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 1st run

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat']

        run_batch() # 2nd run (idempotency hit)

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_heat']

        # It might be slightly less due to cooling between runs, but definitely not heat1 + HEAT_PER_SEQ
        self.assertLessEqual(heat2, heat1)

if __name__ == '__main__':
    unittest.main()

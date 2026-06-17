import unittest
import os
import json
import time
import shutil
from utils.dna_ui import main as run_batch, load_ledger, save_ledger, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_dir = os.path.join(self.project_root, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        # Clean start
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def test_heat_accumulation(self):
        # 1 item = 1.0 heat
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['system_heat'], 1.0, places=1)

    def test_cooling_over_time(self):
        # Manually set high heat in the past
        past_time = time.time() - 100  # 100 seconds ago
        initial_state = {
            'system_heat': 5.0,
            'last_processed_timestamp': past_time,
            'ledger': {}
        }
        save_ledger(self.ledger_path, initial_state)

        # 100 seconds * 0.01 cooling/sec = 1.0 cooling
        # 5.0 - 1.0 = 4.0 current heat
        # Processing 1 item adds 1.0 -> 5.0
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch()

        state = load_ledger(self.ledger_path)
        self.assertAlmostEqual(state['system_heat'], 5.0, places=1)

    def test_thermal_overload_refusal(self):
        # Set heat close to max
        initial_state = {
            'system_heat': 9.5,
            'last_processed_timestamp': time.time(),
            'ledger': {}
        }
        save_ledger(self.ledger_path, initial_state)

        # 1 item adds 1.0 -> 10.5 (> 10.0 MAX_HEAT)
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was NOT added (but updated for cooling, though negligible here)
        state = load_ledger(self.ledger_path)
        self.assertLessEqual(state['system_heat'], 9.5)

    def test_idempotency_no_heat_gain(self):
        # Process once
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")
        run_batch()

        state1 = load_ledger(self.ledger_path)
        heat1 = state1['system_heat']

        # Process same item again - should dedupe and NOT add heat
        # (Though current run_batch implementation skips logic if ALL are deduped)
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch()
        state2 = load_ledger(self.ledger_path)
        # It should actually have LESS heat due to cooling if any time passed
        self.assertLessEqual(state2['system_heat'], heat1)

if __name__ == '__main__':
    unittest.main()

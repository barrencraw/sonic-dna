import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
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
        # VOL prefix = 0.3 heat
        # 10 VOL strings = 3.0 heat
        dna_strings = [f"VOL{str(i).zfill(11)}" for i in range(10)]
        with open(self.input_file, 'w') as f:
            for d in dna_strings:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state["system_heat"], 3.0, places=2)

    def test_thermal_overload_refusal(self):
        # Each VOL = 0.3. MAX_HEAT = 10.0.
        # 34 * 0.3 = 10.2 -> should trigger overload
        dna_strings = [f"VOL{str(i).zfill(11)}" for i in range(40)]
        with open(self.input_file, 'w') as f:
            for d in dna_strings:
                f.write(d + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # It should have stopped before exceeding MAX_HEAT
        self.assertLessEqual(state["system_heat"], MAX_HEAT)
        # Should have processed 33 items (33 * 0.3 = 9.9)
        self.assertEqual(len(state["ledger"]), 33)

    def test_cooling_over_time(self):
        # 1. Generate some heat
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        heat_after_run = state["system_heat"]
        self.assertAlmostEqual(heat_after_run, 0.3, places=2)

        # 2. Wait for cooling (or mock it by adjusting timestamp)
        state["last_processed_timestamp"] -= 60 # 1 minute ago
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 3. Run again (even with already processed DNA to trigger cooling)
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # COOLING_RATE = 0.0083. 60s * 0.0083 = 0.498
        # 0.3 - 0.498 = -0.198 -> capped at 0.0
        self.assertEqual(state["system_heat"], 0.0)

if __name__ == '__main__':
    unittest.main()

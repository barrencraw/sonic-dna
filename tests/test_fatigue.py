import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError, MAX_HEAT, HEAT_PER_ITEM

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # We need enough DNA sequences to reach MAX_HEAT
        count = int(MAX_HEAT / HEAT_PER_ITEM)
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], MAX_HEAT)

    def test_thermal_refusal(self):
        # Exceed MAX_HEAT
        count = int(MAX_HEAT / HEAT_PER_ITEM) + 1
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(count)]

        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")

        # In main(), ThermalOverloadError is caught and handled (printed as HINT)
        # So we should check the ledger or logs instead, or use a lower level call if available.
        # But for now, let's just check that not all were processed.
        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Ledger should have processed up to MAX_HEAT items
        self.assertEqual(len(state['ledger']), int(MAX_HEAT / HEAT_PER_ITEM))

    def test_cooling_over_time(self):
        # 1. Fill heat
        count = int(MAX_HEAT / HEAT_PER_ITEM)
        dnas = [f"VOL{str(i).zfill(11)}" for i in range(count)]
        with open(self.input_file, 'w') as f:
            for d in dnas:
                f.write(d + "\n")
        run_batch()

        # 2. Verify heat is high
        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], MAX_HEAT)

        # 3. Wait for cooling (simulated by manually adjusting timestamp in ledger)
        state['last_processed_timestamp'] -= 100 # Cool for 100 seconds
        # At 0.01/sec, it should cool by 1.0
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # 4. Process one more
        new_dna = "VOL99999999999"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch() # Should succeed now

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)
        self.assertIn(new_dna, state['ledger'])
        # Heat should be around MAX_HEAT. Due to small time passage during run_batch, it might be slightly less.
        self.assertLessEqual(state['system_heat'], MAX_HEAT + 0.01)
        self.assertGreater(state['system_heat'], MAX_HEAT - 0.1)

if __name__ == '__main__':
    unittest.main()

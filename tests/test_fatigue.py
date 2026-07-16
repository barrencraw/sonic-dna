import os
import json
import shutil
import unittest
import time
import datetime
from utils.dna_ui import run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
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
        # HEAT_PER_SEQ = 20.0, MAX_HEAT = 100.0
        dna_list = ["VOL001001001001", "VOL002002002002"]
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(d + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 40.0)
        self.assertIn('last_heat_timestamp', state)

    def test_thermal_lockout(self):
        # 6 sequences * 20.0 = 120.0 (> 100.0)
        dna_list = [f"VOL{i:012d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(d + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Should have processed 5 sequences (100.0 heat) and then hit lockout on the 6th
        self.assertEqual(state['system_heat'], 100.0)
        self.assertEqual(len(state['ledger']), 5)

    def test_heat_dissipation(self):
        # Set initial heat
        initial_state = {
            'ledger': {},
            'system_heat': 100.0,
            'last_heat_timestamp': (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10)).isoformat().replace('+00:00', 'Z')
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(initial_state, f)

        # COOLING_RATE = 2.0 units/sec. 10 seconds = 20.0 reduction.
        # Run empty batch to trigger dissipation
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Heat should be around 80.0
        self.assertLess(state['system_heat'], 81.0)
        self.assertGreater(state['system_heat'], 79.0)

if __name__ == '__main__':
    unittest.main()

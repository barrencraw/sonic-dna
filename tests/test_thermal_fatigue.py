import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger and state
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # VOL0000... gain 0.1
        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # 0.0 - 0.1 (dissipation) -> 0.0.
        # Then + 0.1 = 0.1.
        self.assertAlmostEqual(state['system_heat'], 0.1)

    def test_thermal_noise_application(self):
        # Force heat to 8.0
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 8.0}, f)

        # FRE prefix, root.hz 00440
        # FREZ00440P0000000Z0000
        # Prefix (FRE) + root (band + Hz) + micro (sign + 3) + FM (depth 4 + rate letter + links 4)
        dna = "FREZ00440P0000000Z0000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # FRQ rule schema was actually FRE
        parsed_val = data[0]['parsed']['root']['hz']
        self.assertAlmostEqual(parsed_val, 440 * 0.9)

    def test_thermal_overload_refusal(self):
        # Force heat to 9.9
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 9.9}, f)

        # Next run: 9.9 - 0.1 (dissipation) = 9.8.
        # High amp VOL: VOL1000... gain = 0.1 + 1000/500 = 2.1
        # 9.8 + 2.1 = 11.9 -> OVERLOAD.
        dna = "VOL10000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_cooling_cycle(self):
        # Force heat to 5.0
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        dna = "VOL00000000000" # gain 0.1
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # 5.0 - 0.1 + 0.1 = 5.0
        self.assertAlmostEqual(state['system_heat'], 5.0)

        # Idempotency hit:
        run_batch()
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # 5.0 - 0.1 = 4.9
        self.assertAlmostEqual(state['system_heat'], 4.9)

if __name__ == '__main__':
    unittest.main()

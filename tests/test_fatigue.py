import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.state_path = os.path.join(self.data_folder, 'system_state.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

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

    def test_heat_accumulation_and_degradation(self):
        # 1. Process VOL to increase heat
        # VOL0890... -> amp = 890 -> heat gain = 8.90
        # Passive dissipation at start = -0.5
        # Total heat expected: 0.0 - 0.5 (cap 0) + 8.90 = 8.90
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 8.9)

        # 2. Process CLA and check degradation
        # CLA Z N090 0015
        # Heat 8.9 -> penalty = int(8.9) = 8
        # noise_floor.value: 90 -> 90 - 8 = 82
        # thd: 15 -> 15 + 8*10 = 95
        # Passive dissipation at start of second run: 8.9 - 0.5 = 8.4
        # penalty = int(8.4) = 8
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Find the CLA entry
        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 82)
        self.assertEqual(cla_entry['parsed']['thd'], 95)

    def test_thermal_overload(self):
        # Set heat high manually
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 10.5}, f)

        dna = "VOL01000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_dissipation(self):
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 1.0}, f)

        # Empty input should still dissipate
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 0.5)

    def test_idempotency_heat(self):
        dna_vol = "VOL05000750712" # amp 500 -> heat 5.0
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch() # heat: 0 - 0.5 (0) + 5.0 = 5.0

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 5.0)

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch() # heat: 5.0 - 0.5 = 4.5. DNA is skipped, no heat gain.

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 4.5)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
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
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
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
        # VOL0890 -> amp=890 -> +8.9 heat
        # Dissipation = -0.5
        # Total heat after 1 run: 8.4 (approx)

        dna = "VOL08900000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # Initial: 0.0 -> Dissipate to 0.0 -> +8.9 -> 8.9
        self.assertAlmostEqual(state['system_heat'], 8.9)

    def test_cla_degradation(self):
        # 1. Gain heat
        dna_vol = "VOL05000000000" # +5.0 heat
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")
        run_batch() # heat = 0 - 0.5 + 5.0 = 4.5

        # 2. Process CLA
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")
        run_batch() # heat = 4.5 - 0.5 = 4.0. CLA processed with heat 4.0

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        # Noise floor: 90 - 4 = 86
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)
        # THD: 15 + (4 * 10) = 55
        self.assertEqual(cla_entry['parsed']['thd'], 55)
        self.assertIn("CONSEQUENCE_APPLIED", cla_entry)

    def test_thermal_overload(self):
        # Set heat high
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 10.5}, f)

        dna = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        self.assertEqual(cm.exception.current_heat, 10.0) # 10.5 - 0.5
        self.assertTrue(hasattr(cm.exception, 'REFUSAL_REASON'))

    def test_idempotency_heat(self):
        # Re-processing the same VOL should not increase heat again
        dna = "VOL05000000000"

        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch() # 0 - 0.5 + 5.0 = 4.5

        with open(self.state_path, 'r') as f:
            state1 = json.load(f)
        h1 = state1['system_heat']

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch() # 4.5 - 0.5 = 4.0. No heat gain because skipped.

        with open(self.state_path, 'r') as f:
            state2 = json.load(f)
        h2 = state2['system_heat']

        self.assertEqual(h2, round(h1 - 0.5, 2))

if __name__ == '__main__':
    unittest.main()

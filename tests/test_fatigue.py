import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

class TestFatigueSystem(unittest.TestCase):
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

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger and state (heat = 0.5 to offset dissipation)
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.state_path, 'w') as f:
            json.dump({'system_heat': 0.5}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_refusal(self):
        # 1. Process high-amplitude Volume DNA
        # VOL + amp(0800=80%) + LR(050) + SUR(00) + HEAD(12)
        dna_vol = "VOL08000500012"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        # Heat should be 0.5 (initial) - 0.5 (dissipation) + 8.0 (800/100) = 8.0
        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 8.0)

        # 2. Process Clarity DNA and check penalty
        # CLA + spectral(Z) + noise(N090) + THD(0015)
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        # Heat: 8.0 (current) - 0.5 (dissipation) = 7.5
        with open(self.json_output, 'r') as f:
            data = json.load(f)
            # Find the entry for dna_cla. Note: it might be the 2nd entry in the file.
            cla_entry = next(e for e in data if e['dna'] == dna_cla)
            # noise_floor penalty: 90 - int(7.5) = 90 - 7 = 83
            self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 83)
            # THD penalty: 15 + int(7.5)*10 = 15 + 70 = 85
            self.assertEqual(cla_entry['parsed']['thd'], 85)

        # 3. Increase heat to trigger refusal
        # We need another 3.0+ heat. Another 80% VOL gives 8.0.
        dna_vol2 = "VOL08000500000" # Unique DNA to avoid idempotency
        with open(self.input_file, 'w') as f:
            f.write(dna_vol2 + "\n")

        run_batch()
        # Heat: 7.5 - 0.5 + 8.0 = 15.0

        with open(self.state_path, 'r') as f:
            state = json.load(f)
            self.assertEqual(state['system_heat'], 15.0)

        # 4. Try to process more DNA -> Should be refused
        dna_refused = "VOL01000500000"
        with open(self.input_file, 'w') as f:
            f.write(dna_refused + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)
            refused_entry = next(e for e in data if e['dna'] == dna_refused)
            self.assertIn("Critical thermal threshold reached", refused_entry['error'])

    def test_idempotency_no_double_heat(self):
        dna_vol = "VOL05000500012"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch() # Heat: 0.5 - 0.5 + 5.0 = 5.0

        with open(self.state_path, 'r') as f:
            self.assertEqual(json.load(f)['system_heat'], 5.0)

        # Re-run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch() # Heat: 5.0 - 0.5 (dissipation) + 0 (idempotent) = 4.5

        with open(self.state_path, 'r') as f:
            self.assertEqual(json.load(f)['system_heat'], 4.5)

if __name__ == '__main__':
    unittest.main()

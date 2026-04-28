import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

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

    def test_thermal_accumulation_and_penalty(self):
        # 1. Volume DNA (amp=0890 -> 890 -> +8.9 heat)
        # Starting at 0 heat. Natural cooling: max(0, 0-1) = 0.
        # Heat gain: 8.9. Final: 8.9.
        vol_dna = "VOL08900750712"

        with open(self.input_file, 'w') as f:
            f.write(vol_dna + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.9, places=2)

        # 2. Clarity DNA should be penalized
        # Starting at 8.9 heat.
        # Run batch again: 8.9 - 1.0 = 7.9 heat. Penalty factor 7.
        cla_dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(cla_dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == cla_dna)
        self.assertIn('CONSEQUENCE_APPLIED', cla_entry['world_metadata'])
        # noise_floor value was 90, penalty 7 -> 83
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 83)
        # thd was 15, penalty 7*10=70 -> 85
        self.assertEqual(cla_entry['parsed']['thd'], 85)

    def test_thermal_overload_refusal(self):
        # Accumulate lots of heat using UNIQUE DNA strings
        vol_dna1 = "VOL10000000000" # +10.0 heat
        vol_dna2 = "VOL09990000000" # +9.99 heat

        with open(self.input_file, 'w') as f:
            f.write(f"{vol_dna1}\n{vol_dna2}\n")

        run_batch() # 0 - 1 (0) + 10 + 9.99 = 19.99 heat

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertGreater(state['system_heat'], 10.0)

        # Try Clarity
        cla_dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(cla_dna + "\n")

        run_batch() # 19.99 - 1.0 = 18.99. Still > 10.0.

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry = next(e for e in data if e['dna'] == cla_dna)
        self.assertIn('refusal', cla_entry)
        self.assertIn('REFUSAL_REASON', cla_entry['world_metadata'])

    def test_idempotency_no_double_penalty(self):
        # Process VOL then CLA
        vol_dna = "VOL05000000000" # +5 heat
        cla_dna = "CLAZN0900015"

        with open(self.input_file, 'w') as f:
            f.write(f"{vol_dna}\n{cla_dna}\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        cla_entry_1 = next(e for e in data if e['dna'] == cla_dna)
        nf_1 = cla_entry_1['parsed']['noise_floor']['value']

        # Run again with same CLA
        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Cumulative output should still have only one entry for this CLA
        cla_entries = [e for e in data if e['dna'] == cla_dna]
        self.assertEqual(len(cla_entries), 1)
        self.assertEqual(cla_entries[0]['parsed']['noise_floor']['value'], nf_1)

if __name__ == '__main__':
    unittest.main()

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

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_clarity_penalty(self):
        # 1. Process VOL0890... -> heat gain = 8.9 - 0.5 (dissipation) = 8.4
        dna_vol = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_vol + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # Heat = max(0, 0-0.5) + 8.9 = 8.9
        self.assertAlmostEqual(state['system_heat'], 8.9)

        # 2. Process CLA... -> should have penalty (heat=8.9, int=8)
        # CLA: CLAZN0900015 -> N(90-8) = N082, 0015+(8*10) = 0095
        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        # Dissipation: 8.9 - 0.5 = 8.4
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 8.4)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # The CLA result should be at index 1 (or 0 if we consider this batch)
        # In this specific test, we ran batch twice. Each time it clears input?
        # No, the run_batch doesn't clear input, main.py watcher does.
        # But run_batch appends to json_output.
        cla_entry = next(e for e in data if e['dna'] == dna_cla)
        self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 82) # 90 - 8
        self.assertEqual(cla_entry['parsed']['thd'], 95) # 15 + 80

    def test_thermal_overload_refusal(self):
        # Set heat high
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        dna_cla = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(dna_cla + "\n")

        run_batch()

        # 11.0 - 0.5 = 10.5 (still > 10.0)
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertEqual(ledger[dna_cla]['terminal_outcome'], 'SKIPPED')

        # Output JSON should NOT have this CLA entry
        if os.path.exists(self.json_output):
            with open(self.json_output, 'r') as f:
                data = json.load(f)
            self.assertFalse(any(e['dna'] == dna_cla for e in data))

if __name__ == '__main__':
    unittest.main()

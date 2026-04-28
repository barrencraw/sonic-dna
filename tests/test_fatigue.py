import unittest
import os
import shutil
import tempfile
import json
from utils.dna_ui import main as run_batch

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')

        # Mock rules
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume", "prefix": "VOL",
                "subvars": {"level": {"description": "v", "min": 0, "max": 999, "pad": 3}}
            }, f)
        with open(os.path.join(self.rules_dir, 'rules_Clarity.json'), 'w') as f:
            json.dump({
                "variable": "Clarity", "prefix": "CLA",
                "subvars": {
                    "noise_floor": {"description": "n", "min": 0, "max": 99, "pad": 2, "sign": "+"},
                    "thd": {"description": "t", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_cooling(self):
        # 1. Process Volume DNA -> Gain heat
        with open(self.input_file, 'w') as f:
            f.write("VOL500\n") # level=500 -> +5.0 heat

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # 0.0 (start) - 1.0 (cooling) + 5.0 (VOL500) = 4.0
        # Wait, cooling is applied at the START.
        # Initial state is 0.0.
        # main() starts: system_heat = max(0.0, 0.0 - 1.0) = 0.0.
        # Process VOL500: system_heat += 500 / 100.0 = 5.0.
        self.assertEqual(state['system_heat'], 5.0)

        # 2. Process empty batch -> Natural cooling
        # Actually run_batch returns early if input_file has no DNA strings (read_input_file returns [])
        # BUT natural cooling is applied BEFORE checking if dna_list is empty in my implementation?
        # Let's check dna_ui.py

        # In main():
        # state = load_system_state(state_path)
        # system_heat = state.get("system_heat", 0.0)
        # system_heat = max(0.0, system_heat - 1.0)
        # ...
        # if not dna_list:
        #     save_system_state(state_path, state)
        #     ...
        #     return

        with open(self.input_file, 'w') as f:
            pass # Empty file

        run_batch(data_dir=self.test_dir)
        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # 5.0 - 1.0 = 4.0
        self.assertEqual(state['system_heat'], 4.0)

    def test_clarity_refusal(self):
        # Set high heat
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 12.0}, f)

        with open(self.input_file, 'w') as f:
            f.write("CLA+05050\n") # noise_floor=+05, thd=050

        run_batch(data_dir=self.test_dir)

        # Should be error in ledger
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger["CLA+05050"]["terminal_outcome"], "ERROR")

    def test_clarity_penalty(self):
        # Set moderate heat
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        with open(self.input_file, 'w') as f:
            f.write("CLA+90010\n") # noise_floor=+90, thd=010

        run_batch(data_dir=self.test_dir)

        # Heat 5.0 -> Cooling 1.0 -> Effective heat 4.0
        # noise_floor: 90 - 4 = 86
        # thd: 10 + (4 * 10) = 50

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        parsed = data[0]['parsed']
        self.assertEqual(parsed['noise_floor']['value'], 86)
        self.assertEqual(parsed['thd'], 50)

if __name__ == '__main__':
    unittest.main()

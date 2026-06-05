import os
import json
import shutil
import unittest
import time
from utils.dna_ui import main as run_batch, MAX_HEAT, NOISE_THRESHOLD

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize state
        self.initial_state = {
            "system_heat": 0.0,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(self.initial_state, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # 0.1 heat per normal sequence
        # ENV structure: ENV [curve][time] [curve][time] [level] [curve][time]
        # curve: 1 char, time: 5 chars, level: 3 chars
        # ENV a00000 a00000 000 a00000
        dnas = [f"ENVa0000{i}a00000000a00000" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # Expected heat: 0.5 (0.1 * 5)
        self.assertAlmostEqual(state["system_heat"], 0.5, places=2)

    def test_volume_heat_gain(self):
        # 0.3 heat for VOL
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state["system_heat"], 0.3, places=2)

    def test_cooling(self):
        # Set high heat in the past
        past_time = time.time() - 600 # 10 minutes ago
        state = {
            "system_heat": 5.0,
            "last_processed_timestamp": past_time,
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Run batch (even if empty, it should cool)
        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Cooling rate 0.0083/sec * 600s = 4.98
        # Expected heat: 5.0 - 4.98 = 0.02
        self.assertLess(new_state["system_heat"], 5.0)
        self.assertAlmostEqual(new_state["system_heat"], 0.02, places=1)

    def test_thermal_noise_application(self):
        # Set heat above NOISE_THRESHOLD
        state = {
            "system_heat": NOISE_THRESHOLD + 0.1,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # ENV structure: ENVa00050a00050050a00050
        dna = "ENVa00050a00050050a00050"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Values should be scaled by 0.9
        # 50 * 0.9 = 45
        # data[0] is {dna:..., rule:..., parsed: {attack: {time: 50, curve: 'a'}, ...}}
        parsed = data[0]['parsed']
        self.assertEqual(parsed['attack']['time'], 45)
        self.assertEqual(parsed['decay']['time'], 45)

    def test_thermal_overload_refusal(self):
        # Set heat near MAX_HEAT
        state = {
            "system_heat": MAX_HEAT - 0.05,
            "last_processed_timestamp": time.time(),
            "ledger": {}
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        dna = "ENVa00000a00000000a00000" # Needs 0.1 heat
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        # Heat should NOT have increased because it was refused
        self.assertAlmostEqual(new_state["system_heat"], MAX_HEAT - 0.05, places=2)
        self.assertNotIn(dna, new_state["ledger"])

    def test_idempotency_no_double_heat(self):
        dna = "ENVa00000a00000000a00000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch() # 0.1 gain

        with open(self.ledger_path, 'r') as f:
            state1 = json.load(f)
        self.assertAlmostEqual(state1["system_heat"], 0.1, places=2)

        # Second run with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state2 = json.load(f)

        # Heat should still be 0.1 (minus negligible cooling during execution)
        self.assertAlmostEqual(state2["system_heat"], 0.1, places=1)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
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

    def test_thermal_accumulation_and_refusal(self):
        # 1. Start cold (0.0). Passive dissipation (-0.5) makes it stay at 0.0.
        # Process a sequence with high amp. VOL0890 -> amp=890.
        # Heat gain = 0.1 (base) + 890/500 = 0.1 + 1.78 = 1.88.
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 1.88)

        # 2. Process more to reach noise threshold (>5.0)
        # We need about 3.12 more heat.
        # Let's add 3 more of similar heat.
        # Heat will be 1.88 - 0.5 (dissipation) + 1.88 = 3.26
        # Then 3.26 - 0.5 + 1.88 = 4.64
        # Then 4.64 - 0.5 + 1.88 = 6.02 (Threshold crossed!)

        dnas = ["VOL08900750713", "VOL08900750714", "VOL08900750715"]
        for d in dnas:
            with open(self.input_file, 'w') as f:
                f.write(d + "\n")
            run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertAlmostEqual(state['system_heat'], 6.02, places=2)

        # 3. Verify noise in the last processed DNA
        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # The last one processed (VOL08900750715) should have degraded values.
        # amp was 890. 890 * 0.9 = 801.0
        last_entry = next(e for e in data if e['dna'] == "VOL08900750715")
        self.assertEqual(last_entry['parsed']['amp'], 801.0)

        # 4. Push to refusal (>10.0)
        # Current heat 6.02. Need ~4 more.
        # 6.02 - 0.5 + 1.88 = 7.4
        # 7.4 - 0.5 + 1.88 = 8.78
        # 8.78 - 0.5 + 1.88 = 10.16 (Overload!)
        more_dnas = ["VOL08900750716", "VOL08900750717", "VOL08900750718"]
        for d in more_dnas:
            with open(self.input_file, 'w') as f:
                f.write(d + "\n")
            if d == "VOL08900750718":
                with self.assertRaises(ThermalOverloadError):
                    run_batch()
            else:
                run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertGreater(state['system_heat'], 10.0)

    def test_passive_dissipation(self):
        # Set heat manually
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 5.0}, f)

        # Run batch with no new DNA
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # 5.0 - 0.5 = 4.5
        self.assertEqual(state['system_heat'], 4.5)

    def test_idempotency_no_heat_gain(self):
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()
        with open(self.state_path, 'r') as f:
            state1 = json.load(f)

        # Run again with same DNA
        run_batch()
        with open(self.state_path, 'r') as f:
            state2 = json.load(f)

        # Second run should ONLY dissipate heat, not gain it, because DNA is skipped.
        # state1 was 1.88.
        # state2: 1.88 - 0.5 (dissipation) = 1.38
        self.assertAlmostEqual(state2['system_heat'], 1.38, places=2)

if __name__ == '__main__':
    unittest.main()

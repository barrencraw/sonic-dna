import os
import json
import shutil
import unittest
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

    def test_heat_accumulation_and_noise(self):
        # VOL amp=1000 -> gain = 0.1 + 1000/500 = 2.1
        # Three such sequences = 6.3 (exceeds noise threshold 5.0)
        dna = "VOL10000750712"
        # We need unique DNA strings to avoid idempotency deduplication for testing accumulation
        # or we could clear the ledger. Let's use unique amp values.
        dna1 = "VOL10000750712"
        dna2 = "VOL09990750712"
        dna3 = "VOL09980750712"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n{dna3}\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # Calculation:
        # Passive dissipation: -0.1
        # Seq 1: 2.1 gain -> heat 2.0
        # Seq 2: 0.1 + 999/500 = 2.098 gain -> heat 4.098
        # Seq 3: 0.1 + 998/500 = 2.096 gain -> heat 6.194 (Noise threshold 5.0 hit)

        heat = state["system_heat"]
        self.assertGreater(heat, 5.0)
        self.assertLess(heat, 10.0)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Third sequence should have noise applied
        seq3_data = data[2]['parsed']
        # Original amp was 998. With 0.9 noise, it should be 898.2
        self.assertAlmostEqual(seq3_data['amp'], 898.2)

    def test_cooling_cycle(self):
        # Start with some heat
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 2.0}, f)

        # Low amp VOL cools by 0.5
        dna_cool = "VOL00500750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_cool + "\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)

        # Calculation:
        # Start: 2.0
        # Dissipation: -0.1 -> 1.9
        # Cooling: -0.5 -> 1.4
        self.assertAlmostEqual(state["system_heat"], 1.4)

    def test_thermal_overload(self):
        # Set heat close to limit
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 9.0}, f)

        # High amp VOL gain 2.1 -> total 11.1 (> 10.0 limit)
        dna_hot = "VOL10000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_hot + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still saved
        with open(self.state_path, 'r') as f:
            state = json.load(f)
        self.assertGreater(state["system_heat"], 10.0)

if __name__ == '__main__':
    unittest.main()

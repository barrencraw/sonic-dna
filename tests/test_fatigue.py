import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch

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

        # Backup existing data
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Clean state
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 0.0}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_and_noise(self):
        # VOL0890... -> amp=890. Heat gain = 0.1 + 890/500 = 0.1 + 1.78 = 1.88
        # 3 such sequences = 1.88 * 3 = 5.64.
        # The 3rd one should trigger noise (> 5.0)
        dna1 = "VOL08900750712"
        dna2 = "VOL08900750713" # Vary slightly for uniqueness
        dna3 = "VOL08900750714"

        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n{dna3}\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # Heat after batch: 5.64 - 0.5 (dissipation) = 5.14
        self.assertAlmostEqual(state['system_heat'], 5.14, places=2)

        with open(self.json_output, 'r') as f:
            data = json.load(f)

        # Third entry should have noise applied
        # Original amp=890. 890 * 0.9 = 801
        self.assertEqual(data[0]['parsed']['amp'], 890)
        self.assertEqual(data[1]['parsed']['amp'], 890)
        self.assertAlmostEqual(data[2]['parsed']['amp'], 801, places=0)

    def test_thermal_overload_refusal(self):
        # Max heat is 10.0. Each of these adds 1.88.
        # 6 sequences = 1.88 * 6 = 11.28.
        # The 6th one should trigger overload (> 10.0)
        dnas = [f"VOL089007507{i:02d}" for i in range(10, 16)]

        with open(self.input_file, 'w') as f:
            for dna in dnas:
                f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        # Only first 5 should be in ledger
        self.assertEqual(len(ledger), 5)
        self.assertNotIn(dnas[5], ledger)

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # Heat should have stopped accumulating after the 5th sequence
        # Heat: 1.88 * 5 = 9.4. Minus 0.5 dissipation = 8.9
        self.assertAlmostEqual(state['system_heat'], 8.9, places=2)

if __name__ == '__main__':
    unittest.main()

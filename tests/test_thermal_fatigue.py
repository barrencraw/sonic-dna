import os
import json
import shutil
import unittest
from utils.dna_ui import main as run_batch, load_system_state, save_system_state

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.state_file = os.path.join(self.data_folder, 'system_state.json')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        # Backup
        self.backup_folder = os.path.join(self.project_root, 'data_backup_thermal')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)
        save_system_state(self.project_root, {"system_heat": 0.0})

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation(self):
        # VOL0890... -> amp is 890.
        # delta = 0.1 (base) + 890 / 500 = 0.1 + 1.78 = 1.88
        # batch start: dissipation -0.1.
        # final heat: 0.0 - 0.1 (dissipation, but clamped to 0) + 1.88 = 1.88
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        state = load_system_state(self.project_root)
        self.assertAlmostEqual(state['system_heat'], 1.88, places=2)

    def test_thermal_noise_application(self):
        # Set heat to 8.0
        save_system_state(self.project_root, {"system_heat": 8.0})

        # DNA for Volume. amp=0500 (50.0%)
        dna = "VOL05000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Check output
        json_out = os.path.join(self.output_folder, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)

        # amp should be 500 * 0.9 = 450
        self.assertEqual(data[0]['parsed']['amp'], 450.0)
        self.assertGreater(data[0]['heat_level'], 7.0)

    def test_cooling_cycle(self):
        # Set heat to 5.0
        save_system_state(self.project_root, {"system_heat": 5.0})

        # VOL0050... -> amp is 50 (< 100).
        # delta = -0.5
        # batch start: dissipation -0.1 -> 4.9
        # final heat: 4.9 - 0.5 = 4.4
        dna = "VOL00500000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        state = load_system_state(self.project_root)
        self.assertAlmostEqual(state['system_heat'], 4.4, places=2)

    def test_thermal_overload_refusal(self):
        # Set heat to 9.5
        save_system_state(self.project_root, {"system_heat": 9.5})

        # delta = 0.1 + 890/500 = 1.88
        # 9.5 - 0.1 + 1.88 = 11.28 > 10.0
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        from utils.dna_ui import ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was updated before crashing
        state = load_system_state(self.project_root)
        self.assertGreater(state['system_heat'], 10.0)

    def test_persistence_across_runs(self):
        dna = "VOL01000000000" # amp=100. delta = 0.1 + 100/500 = 0.3

        # Run 1: 0.0 -> -0.1 (clamped 0) + 0.3 = 0.3
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")
        run_batch()

        state1 = load_system_state(self.project_root)
        self.assertAlmostEqual(state1['system_heat'], 0.3, places=2)

        # Run 2: 0.3 -> 0.2 (dissipation) + 0.3 (new DNA, same string but let's assume it's processed again for test)
        # We need to use a DIFFERENT DNA or clear ledger
        os.remove(self.ledger_path)

        run_batch()
        state2 = load_system_state(self.project_root)
        self.assertAlmostEqual(state2['system_heat'], 0.5, places=2)

if __name__ == '__main__':
    unittest.main()

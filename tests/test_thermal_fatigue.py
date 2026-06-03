import unittest
import os
import shutil
import tempfile
import json
import time
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.rule_file_other = os.path.join(self.rules_dir, 'rules_Freq.json')
        with open(self.rule_file_other, 'w') as f:
            json.dump({
                "variable": "Frequency",
                "prefix": "F",
                "subvars": {
                    "hz": {"description": "freq", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        with open(input_file, 'w') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def test_heat_accumulation(self):
        # VOL prefix = 0.3 heat
        # Need 34 strings to exceed 10.0
        dna_list = [f"VOL{str(i).zfill(3)}" for i in range(5)]
        self.write_dna(dna_list)

        run_batch()

        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
            # 5 * 0.3 = 1.5
            self.assertAlmostEqual(state['system_heat'], 1.5)

    def test_thermal_noise_application(self):
        # Need > 7.0 heat to trigger noise. 24 VOL strings * 0.3 = 7.2
        dna_list = [f"VOL{str(i).zfill(3)}" for i in range(24)]
        # Add one more that will have noise applied
        dna_list.append("F500")
        self.write_dna(dna_list)

        run_batch()

        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            data = json.load(f)
            # Find the F500 entry (it's the last one)
            f_entry = data[-1]
            self.assertEqual(f_entry['dna'], 'F500')
            # 500 * 0.9 = 450.0
            self.assertEqual(f_entry['parsed']['hz'], 450.0)

    def test_thermal_overload_refusal(self):
        # 34 VOL strings * 0.3 = 10.2 -> should fail
        dna_list = [f"VOL{str(i).zfill(3)}" for i in range(34)]
        self.write_dna(dna_list)

        run_batch()

        # In current design, main catches ThermalOverloadError and breaks.
        # Check that one item is NOT in the ledger.
        ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')
        with open(ledger_path, 'r') as f:
            ledger = json.load(f)
            # Should have 33 items, not 34
            self.assertEqual(len(ledger), 33)

        # State should still be persisted with high heat
        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state = json.load(f)
            self.assertGreater(state['system_heat'], 10.0)

    def test_cooling_cycle(self):
        # Add some heat
        self.write_dna(["VOL001"])
        run_batch()

        state_path = os.path.join(self.data_dir, 'system_state.json')
        with open(state_path, 'r') as f:
            state_before = json.load(f)
            self.assertEqual(state_before['system_heat'], 0.3)

        # Manually set last_tick to 1 minute ago
        state_before['last_tick'] -= 60
        with open(state_path, 'w') as f:
            json.dump(state_before, f)

        # Run batch again (empty or same)
        # 60 seconds * 0.0083 = 0.498 reduction. 0.3 - 0.498 = 0.0
        self.write_dna([])
        run_batch()

        with open(state_path, 'r') as f:
            state_after = json.load(f)
            self.assertEqual(state_after['system_heat'], 0.0)

if __name__ == '__main__':
    unittest.main()

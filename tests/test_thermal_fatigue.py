import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for tests
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup folder structure
        os.makedirs("data/raw")
        os.makedirs("data/output")
        os.makedirs("rules")

        # Mock a Volume rule
        volume_rule = {
            "variable": "Volume",
            "prefix": "VOL",
            "subvars": {
                "amp": {"min": 0, "max": 1000, "pad": 4, "description": "amp"}
            }
        }
        with open("rules/rules_Volume.json", "w") as f:
            json.dump(volume_rule, f)

        self.input_file = "data/raw/toSequence.txt"
        self.state_file = "data/system_state.json"

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # Process one sequence: 0.1 (base) + 500/500 (amp) = 1.1
        # Passive dissipation -0.1 at start.
        # Initial 0.0 -> -0.1 (passive) -> 0.0 (max) -> +1.1 = 1.1
        with open(self.input_file, "w") as f:
            f.write("VOL0500\n")

        run_batch()

        with open(self.state_file, "r") as f:
            state = json.load(f)
        self.assertAlmostEqual(state["system_heat"], 1.1)

    def test_cooling_cycle(self):
        # Set initial heat high
        with open(self.state_file, "w") as f:
            json.dump({"system_heat": 5.0}, f)

        # Cooling sequence: VOL0050 (amp=50 < 100) -> gain = -0.5
        # 5.0 -> 4.9 (passive) -> -0.5 = 4.4
        with open(self.input_file, "w") as f:
            f.write("VOL0050\n")

        run_batch()

        with open(self.state_file, "r") as f:
            state = json.load(f)
        self.assertAlmostEqual(state["system_heat"], 4.4)

    def test_thermal_noise(self):
        # Set heat just below noise threshold (7.0)
        # We need a sequence that pushes it over 7.0
        # 6.5 -> 6.4 (passive) -> +1.1 = 7.5
        with open(self.state_file, "w") as f:
            json.dump({"system_heat": 6.5}, f)

        with open(self.input_file, "w") as f:
            f.write("VOL0500\n")

        run_batch()

        # Check output JSON for noise (multiplied by 0.9)
        output_json = "data/output/toSequence_parsed.json"
        with open(output_json, "r") as f:
            data = json.load(f)

        # amp was 500, with noise should be 500 * 0.9 = 450
        self.assertAlmostEqual(data[0]["parsed"]["amp"], 450.0)

    def test_overload_refusal(self):
        # Set heat high
        with open(self.state_file, "w") as f:
            json.dump({"system_heat": 9.5}, f)

        # Sequence that causes overload (> 10.0)
        # 9.5 -> 9.4 (passive) -> +1.1 = 10.5
        with open(self.input_file, "w") as f:
            f.write("VOL0500\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still recorded
        with open(self.state_file, "r") as f:
            state = json.load(f)
        self.assertGreater(state["system_heat"], 10.0)

if __name__ == "__main__":
    unittest.main()

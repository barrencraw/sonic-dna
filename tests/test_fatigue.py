import unittest
import os
import shutil
import json
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        # Create a temp project root
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup folders
        os.makedirs("data/raw")
        os.makedirs("data/output")
        # Symlink rules
        os.symlink(os.path.join(self.old_cwd, "rules"), "rules")

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_lines):
        with open("data/raw/toSequence.txt", "w") as f:
            for line in dna_lines:
                f.write(line + "\n")

    def get_heat(self):
        state_path = "data/system_state.json"
        if os.path.exists(state_path):
            with open(state_path, "r") as f:
                return json.load(f).get("system_heat", 0.0)
        return 0.0

    def test_heat_accumulation(self):
        # VOL05000750712 -> amp=500. heat_gain = 0.1 + 500/500 = 1.1
        # Initial 0.0 -> Passive dissipation (max(0, -0.1)) = 0.0.
        # Gain 1.1 -> Total 1.1
        self.write_dna(["VOL05000750712"])
        run_batch()
        self.assertEqual(self.get_heat(), 1.1)

        # Second run:
        # Initial 1.1 -> Passive dissipation (1.1 - 0.1) = 1.0.
        # Gain 1.1 -> Total 2.1
        self.write_dna(["VOL05000750713"]) # different to avoid idempotency
        run_batch()
        self.assertEqual(self.get_heat(), 2.1)

    def test_cooling_cycle(self):
        # Set initial heat
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 5.0}, f)

        # VOL00500750712 -> amp=50. heat_gain = -0.5
        # Passive dissipation = -0.1. Net = -0.6. Total 4.4
        self.write_dna(["VOL00500750712"])
        run_batch()
        self.assertEqual(self.get_heat(), 4.4)

    def test_thermal_noise_application(self):
        # Set heat to trigger noise (> 5.0)
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 6.0}, f)

        # VOL05000750712 -> amp=500.
        # Values should be multiplied by 0.9
        self.write_dna(["VOL05000750712"])
        run_batch()

        with open("data/output/toSequence_parsed.json", "r") as f:
            data = json.load(f)
            parsed = data[0]['parsed']
            # amp was 500, should be 450.0
            self.assertEqual(parsed['amp'], 450.0)

    def test_thermal_overload_refusal(self):
        # Set heat close to limit (10.0)
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 9.5}, f)

        # VOL05000750712 -> heat_gain = 1.1. 9.5 + 1.1 = 10.6 > 10.0
        self.write_dna(["VOL05000750712"])

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still updated (passive dissipation applied before loop)
        # 9.5 - 0.1 = 9.4
        self.assertEqual(self.get_heat(), 9.4)

if __name__ == "__main__":
    unittest.main()

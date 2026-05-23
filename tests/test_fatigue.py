import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        # Create a temporary sandbox for testing
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup folder structure
        os.makedirs("data/raw")
        os.makedirs("data/output")
        # Symlink rules folder from original project root
        os.symlink(os.path.join(self.old_cwd, "rules"), "rules")

        # Initialize state
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 0.0}, f)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open("data/raw/toSequence.txt", "w") as f:
            for dna in dna_list:
                f.write(dna + "\n")

    def get_heat(self):
        with open("data/system_state.json", "r") as f:
            return json.load(f)["system_heat"]

    def test_heat_accumulation(self):
        # VOL0500... -> amp=500 -> heat_gain = 0.1 + (500/500) = 1.1
        # system_heat starts at 0.0. Passive dissipation = max(0, 0-0.1) = 0.0
        # Total heat after 1 sequence: 0.0 + 1.1 = 1.1
        self.write_dna(["VOL05000000000"])
        run_batch()
        self.assertAlmostEqual(self.get_heat(), 1.1)

    def test_thermal_noise(self):
        # amp=1000 -> heat_gain = 0.1 + (1000/500) = 2.1
        # 1 run with 3 items of amp=1000:
        # Passive: 0 -> 0
        # 1: 0 + 2.1 = 2.1
        # 2: 2.1 + 2.1 = 4.2
        # 3: 4.2 + 2.1 = 6.3 (> 5.0 threshold)

        self.write_dna(["VOL10000000000", "VOL10000000001", "VOL10000000002"])
        run_batch()
        self.assertAlmostEqual(self.get_heat(), 6.3)

        # Check parsed output for noise (0.9 multiplier)
        with open("data/output/toSequence_parsed.json", "r") as f:
            parsed = json.load(f)
            # The 3rd sequence should have noise applied
            # Original amp was 1000. 1000 * 0.9 = 900
            self.assertEqual(parsed[2]['parsed']['amp'], 900)

    def test_thermal_overload_refusal(self):
        # Force high heat
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 9.5}, f)

        # VOL1000 -> gain 2.1.
        # Passive: 9.5 -> 9.4
        # Item: 9.4 + 2.1 = 11.5 (> 10.0)
        self.write_dna(["VOL10000000000"])
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still persisted even on failure (passive dissipation was applied)
        self.assertAlmostEqual(self.get_heat(), 9.4)

    def test_cooling_cycle(self):
        with open("data/system_state.json", "w") as f:
            json.dump({"system_heat": 5.0}, f)

        # amp=050 (< 100) -> heat_gain = -0.5
        self.write_dna(["VOL00500000000"])
        run_batch()
        # 5.0 - 0.1 (passive) - 0.5 (cooling) = 4.4
        self.assertAlmostEqual(self.get_heat(), 4.4)

    def test_idempotency_no_heat_gain(self):
        self.write_dna(["VOL05000000000"])
        run_batch()
        h1 = self.get_heat() # 1.1

        # Run again with same DNA - should hit idempotency and NOT increase heat
        # But passive dissipation still applies!
        run_batch()
        h2 = self.get_heat()

        # h2 = h1 - 0.1 = 1.0
        self.assertAlmostEqual(h2, h1 - 0.1)

if __name__ == "__main__":
    unittest.main()

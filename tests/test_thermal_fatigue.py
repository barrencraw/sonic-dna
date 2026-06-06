import unittest
import os
import json
import shutil
import tempfile
import time
from utils.dna_ui import main as run_batch, load_ledger, save_ledger, MAX_HEAT, NOISE_THRESHOLD

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, "data")
        self.raw_dir = os.path.join(self.data_dir, "raw")
        self.output_dir = os.path.join(self.data_dir, "output")
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy rules folder to test_dir
        self.rules_dir = os.path.join(self.test_dir, "rules")
        shutil.copytree("rules", self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, "toSequence.txt")
        self.ledger_path = os.path.join(self.data_dir, "processed_ledger.json")

        # Patch os.getcwd in dna_ui to use our test_dir
        import utils.dna_ui
        self.old_getcwd = os.getcwd
        os.getcwd = lambda: self.test_dir

    def tearDown(self):
        os.getcwd = self.old_getcwd
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # Create input with several DNA strings
        # Use unique DNA strings to bypass idempotency/dedupe
        # Volume structure: VOL + amp(4) + lr(3) + sur(2) + head(2) = 14 chars
        dna_strings = [f"VOL089007507{i:02d}" for i in range(5)]
        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(f"{dna}\n")

        run_batch(correlation_id="test-heat")

        state = load_ledger(self.ledger_path)
        # VOL is 0.3 each. 5 * 0.3 = 1.5
        self.assertAlmostEqual(state["system_heat"], 1.5)

    def test_noise_threshold(self):
        # Reach the noise threshold (7.0)
        # Need 24 VOL strings (24 * 0.3 = 7.2)
        dna_strings = [f"VOL089007507{i:02d}" for i in range(25)]
        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(f"{dna}\n")

        run_batch(correlation_id="test-noise")

        # Check output JSON for degraded status
        json_path = os.path.join(self.output_dir, "toSequence_parsed.json")
        with open(json_path, 'r') as f:
            data = json.load(f)

        # The 24th item (index 23) should be 24 * 0.3 = 7.2 > 7.0
        self.assertEqual(data[23]["thermal_status"], "degraded")
        self.assertEqual(data[0]["thermal_status"], "clean")

    def test_thermal_overload_refusal(self):
        # Reach the max heat (10.0)
        # Need 34 VOL strings (34 * 0.3 = 10.2)
        dna_strings = [f"VOL089007507{i:02d}" for i in range(40)]
        with open(self.input_file, 'w') as f:
            for dna in dna_strings:
                f.write(f"{dna}\n")

        run_batch(correlation_id="test-overload")

        state = load_ledger(self.ledger_path)
        # Should stop before exceeding 10.0
        self.assertLessEqual(state["system_heat"], MAX_HEAT)

        # Check that not all items were processed
        self.assertLess(len(state["ledger"]), 40)

    def test_passive_cooling(self):
        # Set initial heat
        state = {
            "system_heat": 5.0,
            "last_processed_timestamp": time.time() - 600, # 10 mins ago
            "ledger": {}
        }
        save_ledger(self.ledger_path, state)

        # Run empty batch to trigger cooling
        with open(self.input_file, 'w') as f:
            pass

        run_batch(correlation_id="test-cooling")

        new_state = load_ledger(self.ledger_path)
        # 10 mins = 600 secs. 600 * 0.0083 = 4.98
        # 5.0 - 4.98 = 0.02
        self.assertAlmostEqual(new_state["system_heat"], 0.02, places=2)

if __name__ == "__main__":
    unittest.main()

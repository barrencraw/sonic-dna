import unittest
import os
import json
import shutil
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.raw_dir = os.path.join(self.project_root, 'data', 'raw')
        self.output_dir = os.path.join(self.project_root, 'data', 'output')
        self.state_path = os.path.join(self.project_root, 'data', 'system_state.json')
        self.ledger_path = os.path.join(self.project_root, 'data', 'processed_ledger.json')
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

        # Clear files
        for p in [self.state_path, self.ledger_path, self.input_file]:
            if os.path.exists(p):
                os.remove(p)

    def tearDown(self):
        # Optional: cleanup
        pass

    def test_heat_accumulation_and_impact(self):
        # 1. Process Volume DNA to increase heat
        # VOL + amp(0500) + lr(050) + sur(00) + head(12) = VOL05000500012
        # Heat gain = 500 / 100.0 = 5.0
        # Passive dissipation = -0.5
        # Total heat after 1st batch = 4.5
        with open(self.input_file, 'w') as f:
            f.write("VOL05000500012\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state = json.load(f)
        # Heat gain is applied AFTER dissipation.
        # Initial 0.0 -> -0.5 (clamped to 0.0) -> +5.0 = 5.0
        self.assertEqual(state['system_heat'], 5.0)

        # 2. Process Clarity DNA and check impact
        # CLA + flat(Z) + noise(N090) + thd(0015) = CLAZN0900015
        # 2nd batch: Initial 5.0 -> Dissipation 4.5
        # Penalty at heat 4.5:
        # THD increase: int(4.5)*10 = 40. New THD = 15 + 40 = 55.
        # Noise floor elevation: -int(4.5) = -4. New NF = 90 - 4 = 86.
        # Final heat after 2nd batch = 4.5 (no heat gain from CLA)

        with open(self.input_file, 'w') as f:
            f.write("CLAZN0900015\n")

        run_batch()

        # Check results in JSON
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(json_out, 'r') as f:
            results = json.load(f)

        cla_result = next(r for r in results if r['dna'] == "CLAZN0900015")
        self.assertEqual(cla_result['parsed']['thd'], 55)
        self.assertEqual(cla_result['parsed']['noise_floor']['value'], 86)

    def test_thermal_overload(self):
        # Set heat to high value
        with open(self.state_path, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        with open(self.input_file, 'w') as f:
            f.write("VOL01000500012\n")

        # Passive dissipation: 11.0 - 0.5 = 10.5. Still > 10.0.
        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_idempotency_no_double_heat(self):
        # Process VOL twice
        with open(self.input_file, 'w') as f:
            f.write("VOL05000500012\n")

        run_batch()

        with open(self.state_path, 'r') as f:
            state1 = json.load(f)
        heat1 = state1['system_heat'] # Should be 5.0

        # Run again with same input
        # It should be skipped by ledger, so no new heat gain.
        # HOWEVER, main() always applies passive dissipation at the start.
        # So heat should actually decrease!
        run_batch()

        with open(self.state_path, 'r') as f:
            state2 = json.load(f)
        heat2 = state2['system_heat']

        self.assertEqual(heat2, max(0.0, round(heat1 - 0.5, 2)))

if __name__ == '__main__':
    unittest.main()

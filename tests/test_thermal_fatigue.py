import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import (
    main as run_batch,
    load_system_state,
    save_system_state,
    ThermalOverloadError
)

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Setup folder structure
        os.makedirs('data/raw')
        os.makedirs('data/output')
        os.makedirs('rules')

        # Copy a rule for testing
        source_rule = os.path.join(self.old_cwd, 'rules', 'rules_Volume.json')
        shutil.copy(source_rule, 'rules/rules_Volume.json')

        self.state_path = 'data/system_state.json'
        self.input_path = 'data/raw/toSequence.txt'
        self.ledger_path = 'data/processed_ledger.json'

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation(self):
        # VOL08900750712 -> amp is 890
        # delta = 0.1 + (890 / 500.0) = 0.1 + 1.78 = 1.88
        # main() applies -0.1 passive cooling at start
        # Expected heat after 1 run: 0.0 - 0.1 (clamped to 0) + 1.88 = 1.88

        with open(self.input_path, 'w') as f:
            f.write("VOL08900750712\n")

        run_batch()

        state = load_system_state(self.state_path)
        self.assertAlmostEqual(state['system_heat'], 1.88)

    def test_noise_application(self):
        # Force high heat
        save_system_state(self.state_path, {'system_heat': 8.0})

        with open(self.input_path, 'w') as f:
            f.write("VOL01000750712\n")

        run_batch()

        with open('data/output/toSequence_parsed.json', 'r') as f:
            data = json.load(f)
            # Original amp was 100, should be 90 now
            self.assertAlmostEqual(data[0]['parsed']['amp'], 90.0)

    def test_overload_refusal(self):
        # Force near-limit heat
        save_system_state(self.state_path, {'system_heat': 9.5})

        # VOL0890... delta is 1.88. 9.5 + 1.88 > 10.0
        with open(self.input_path, 'w') as f:
            f.write("VOL08900750712\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        state = load_system_state(self.state_path)
        # Heat should still have increased by delta
        self.assertAlmostEqual(state['system_heat'], 9.5 - 0.1 + 1.88)

    def test_idempotency_and_no_silent_drains(self):
        # Ensure processing twice doesn't double-drain/heat
        with open(self.input_path, 'w') as f:
            f.write("VOL01000750712\n")

        run_batch()
        state1 = load_system_state(self.state_path)
        heat1 = state1['system_heat']

        # Run again with same input
        run_batch()
        state2 = load_system_state(self.state_path)
        heat2 = state2['system_heat']

        # Second run should only apply passive cooling because input is already in ledger
        # heat2 = max(0, heat1 - 0.1)
        self.assertAlmostEqual(heat2, max(0.0, heat1 - 0.1))

if __name__ == '__main__':
    unittest.main()

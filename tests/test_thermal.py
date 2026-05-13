import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalManagement(unittest.TestCase):
    def setUp(self):
        # Create a temporary environment
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.out_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.out_dir)

        # Link rules
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.symlink(os.path.abspath('rules'), self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_base(self):
        """Verify base heat increases by 0.1 per unique sequence."""
        # Use 6 DIFFERENT sequences to avoid idempotency deduplication
        dna = "\n".join([f"TEX0{i}321D007600137Z" for i in range(6)])
        with open(self.input_file, 'w') as f:
            f.write(dna)

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        # 6 sequences = 0.6 gain. Dissipation starts at 0.0 -> 0.0.
        # Total = 0.6
        self.assertAlmostEqual(state['system_heat'], 0.6)

    def test_heat_accumulation_volume(self):
        """Verify Volume strings add extra heat (amp / 500)."""
        # VOL0500... -> amp=500. Heat gain = 0.1 (base) + 500/500 (1.0) = 1.1
        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna)

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 1.1)

    def test_passive_dissipation(self):
        """Verify heat dissipates by 0.5 per run."""
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 1.0}, f)

        # Empty run
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        with open(self.state_file, 'r') as f:
            state = json.load(f)

        self.assertAlmostEqual(state['system_heat'], 0.5)

    def test_thermal_noise(self):
        """Verify values are degraded by 10% when heat > 5.0."""
        # Initial heat = 6.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 6.0}, f)

        dna = "VOL08000750712" # amp 800
        with open(self.input_file, 'w') as f:
            f.write(dna)

        run_batch()

        # Check parsed JSON
        out_json = os.path.join(self.out_dir, 'toSequence_parsed.json')
        with open(out_json, 'r') as f:
            data = json.load(f)

        # Original amp was 800, should be 800 * 0.9 = 720
        self.assertEqual(data[0]['parsed']['amp'], 720.0)

    def test_thermal_refusal(self):
        """Verify ThermalOverloadError is raised when heat >= 10.0."""
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 11.0}, f)

        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna)

        with self.assertRaises(ThermalOverloadError):
            run_batch()

    def test_idempotency_no_heat(self):
        """Verify already processed strings don't add heat."""
        # 1. Process once
        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna)
        run_batch()

        with open(self.state_file, 'r') as f:
            state1 = json.load(f)

        # 2. Process again (same string)
        run_batch()

        with open(self.state_file, 'r') as f:
            state2 = json.load(f)

        # state2 heat should be state1 heat - 0.5 (only dissipation)
        self.assertAlmostEqual(state2['system_heat'], max(0.0, state1['system_heat'] - 0.5))

if __name__ == '__main__':
    unittest.main()

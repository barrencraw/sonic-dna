import os
import json
import shutil
import tempfile
import unittest
import sys
from unittest import mock

# Mocking numpy and scipy to avoid dependency issues in the test environment if needed,
# but dna_ui/dna_calculator don't seem to strictly require them for Volume parsing.
# However, if they are imported elsewhere, we might need to mock them.
try:
    import numpy
except ImportError:
    sys.modules["numpy"] = mock.MagicMock()
try:
    import scipy
except ImportError:
    sys.modules["scipy"] = mock.MagicMock()

from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup a clean sandbox
        self.base_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.base_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Copy rules folder instead of symlinking to be safer across platforms
        shutil.copytree(os.path.abspath('rules'), os.path.join(self.base_dir, 'rules'))

        # Change CWD
        self.old_cwd = os.getcwd()
        os.chdir(self.base_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.base_dir)

    def test_thermal_accumulation_and_noise(self):
        input_file = os.path.join('data', 'raw', 'toSequence.txt')
        state_file = os.path.join('data', 'system_state.json')
        output_file = os.path.join('data', 'output', 'toSequence_parsed.json')

        # 1. First batch: Moderate heat
        # VOL0500... -> amp 500. Heat gain = 0.1 + (500/500) = 1.1.
        # Total heat after 1st batch = max(0, 0.0 - 0.5) + 1.1 = 1.1.
        with open(input_file, 'w') as f:
            f.write("VOL05000500512\n")

        run_batch()

        with open(state_file, 'r') as f:
            state = json.load(f)
            self.assertAlmostEqual(state['system_heat'], 1.1, places=2)

        # 2. Second batch: Push to threshold 5.0
        # Add 4 more NEW sequences. Each adds 1.1.
        # Total heat = (1.1 - 0.5) + (4 * 1.1) = 0.6 + 4.4 = 5.0. (Still no noise as 5.0 <= 5.0)
        with open(input_file, 'w') as f:
            for i in range(1, 5):
                f.write(f"VOL050{i}0500512\n") # Use different strings to avoid idempotency

        run_batch()

        with open(state_file, 'r') as f:
            state = json.load(f)
            # Use delta for more flexible float comparison
            self.assertAlmostEqual(state['system_heat'], 5.0, delta=0.1)

        # 3. Third batch: Trigger noise
        # Current heat ~5.0. Dissipates by 0.5. Next item: amp 600.
        # gain = 0.1 + 600/500 = 1.3.
        # ~4.5 + 1.3 = ~5.8. Noise should trigger for this item as 5.8 > 5.0.
        with open(input_file, 'w') as f:
            f.write("VOL06000500512\n")

        run_batch()

        with open(output_file, 'r') as f:
            parsed = json.load(f)
            # Find the last entry (the one that triggered noise)
            last_entry = [p for p in parsed if p['dna'] == "VOL06000500512"][0]
            # amp was 600. Scaled by 0.9 = 540.
            # Use assertAlmostEqual for floats after scaling
            self.assertAlmostEqual(last_entry['parsed']['amp'], 540.0, places=1)

    def test_thermal_overload(self):
        input_file = os.path.join('data', 'raw', 'toSequence.txt')
        state_file = os.path.join('data', 'system_state.json')

        # Force high heat in state file
        os.makedirs('data', exist_ok=True)
        with open(state_file, 'w') as f:
            json.dump({"system_heat": 9.5}, f)

        # High amp: gain 0.1 + 1000/500 = 2.1.
        # 9.5 - 0.5 + 2.1 = 11.1 > 10.0.
        with open(input_file, 'w') as f:
            f.write("VOL10000500512\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Verify heat was still saved (in finally block)
        with open(state_file, 'r') as f:
            state = json.load(f)
            # It shouldn't have added the heat for the failed item, but it should have applied dissipation
            # 9.5 - 0.5 = 9.0
            self.assertAlmostEqual(state['system_heat'], 9.0, places=2)

if __name__ == '__main__':
    unittest.main()

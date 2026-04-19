import os
import json
import shutil
import unittest
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestAtomicityAndFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock rules folder by linking to real one
        self.real_rules = os.path.join(os.getcwd(), 'rules')
        os.symlink(self.real_rules, os.path.join(self.test_dir, 'rules'))

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_fatigue_accumulation_and_refusal(self):
        # 1. Process high-amplitude Volume DNA to increase heat
        # VOL rule: VOL + amp(4) + lr(3) + sur(2) + head(2)
        # amp is first 4 digits. 0900 -> +9.0 heat
        high_vol = "VOL09000500512"
        with open(self.input_file, 'w') as f:
            f.write(high_vol + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # 0.0 (initial) -> natural cooling(0.0) + 9.0 (gain) = 9.0
        self.assertEqual(state['system_heat'], 9.0)

        # 2. Process another Volume DNA to exceed 10.0
        with open(self.input_file, 'w') as f:
            f.write("VOL03000500512\n") # +3.0 heat

        run_batch(data_dir=self.test_dir)

        with open(self.state_file, 'r') as f:
            state = json.load(f)
        # 9.0 (start) - 1.0 (natural cooling) + 3.0 (gain) = 11.0
        self.assertEqual(state['system_heat'], 11.0)

        # 3. Clarity DNA should still pass if heat at START of processing is <= 10.0
        # For the next run, it starts at 11.0. Natural cooling: 11.0 - 1.0 = 10.0.
        # Threshold is > 10.0, so 10.0 should JUST pass.
        # CLA rule: CLA + spectral_flat(1) + noise_floor(N+3) + thd(4)
        clarity_dna = "CLAZN0900015"
        with open(self.input_file, 'w') as f:
            f.write(clarity_dna + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            parsed = json.load(f)
        # Find the entry for clarity_dna
        entry = next(e for e in parsed if e['dna'] == clarity_dna)
        self.assertIn('parsed', entry)
        # noise_floor.value: 90 - 10 (heat at start of loop was 11.0 - 1.0 = 10.0) = 80
        # Note: the rules define noise_floor as N + 0-120. Decreasing 90 -> 80 means raising floor from -90 to -80.
        self.assertEqual(entry['parsed']['noise_floor']['value'], 80)

        # 4. Now heat at end of run 3 was 10.0 (no gain from Clarity).
        # Next run natural cooling: 10.0 - 1.0 = 9.0.
        # Push it over 10.0 again.
        with open(self.input_file, 'w') as f:
            f.write("VOL05000000012\n") # +5.0 heat
        run_batch(data_dir=self.test_dir)

        # Heat: 10.0 - 1.0 + 5.0 = 14.0
        with open(self.state_file, 'r') as f:
            state = json.load(f)
        self.assertEqual(state['system_heat'], 14.0)

        # 5. Clarity DNA should now be refused (14.0 - 1.0 = 13.0 > 10.0)
        clarity_dna_2 = "CLAZN0800015"
        with open(self.input_file, 'w') as f:
            f.write(clarity_dna_2 + "\n")

        run_batch(data_dir=self.test_dir)

        with open(self.json_output, 'r') as f:
            parsed = json.load(f)

        entry = next(e for e in parsed if e['dna'] == clarity_dna_2)
        self.assertEqual(entry['error_type'], "ThermalRefusal")
        self.assertIn("exceeds threshold 10.0", entry['error'])

    def test_atomicity_boundary(self):
        # We can't easily simulate a mid-write crash without mocking 'os.replace'
        # but we can verify all files are created together.
        dna = "VOL05000500512"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch(data_dir=self.test_dir)

        self.assertTrue(os.path.exists(self.json_output))
        self.assertTrue(os.path.exists(self.ledger_file))
        self.assertTrue(os.path.exists(self.state_file))

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertIn(dna, ledger)

if __name__ == '__main__':
    unittest.main()

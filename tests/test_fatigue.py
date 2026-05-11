import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as dna_main

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.out_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.out_dir)
        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

        # Create minimal rules folder
        self.rules_dir = os.path.join(self.test_dir, 'rules')
        os.makedirs(self.rules_dir)
        # Copy real rules for Volume and Clarity
        real_rules_dir = os.path.join(self.old_cwd, 'rules')
        shutil.copy(os.path.join(real_rules_dir, 'rules_Volume.json'), self.rules_dir)
        shutil.copy(os.path.join(real_rules_dir, 'rules_Clarity.json'), self.rules_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w') as f:
            for d in dna_list:
                f.write(f"{d}\n")

    def get_heat(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f).get('system_heat', 0.0)
        return 0.0

    def test_heat_accumulation_and_dissipation(self):
        # VOL08000000000 -> amp=800 -> +8.0 heat
        self.write_dna(["VOL08000000000"])
        dna_main(data_dir=self.data_dir)

        # 8.0 gain - 0.5 dissipation = 7.5
        self.assertEqual(self.get_heat(), 7.5)

        # Run again with empty file -> 7.5 - 0.5 = 7.0
        self.write_dna([])
        dna_main(data_dir=self.data_dir)
        self.assertEqual(self.get_heat(), 7.0)

    def test_clarity_penalty(self):
        # First, heat up the system
        # VOL05000000000 -> amp=500 -> +5.0 heat.
        # Batch end: 5.0 - 0.5 = 4.5 heat.
        self.write_dna(["VOL05000000000"])
        dna_main(data_dir=self.data_dir)
        self.assertEqual(self.get_heat(), 4.5)

        # Now process Clarity string
        # CLAZN0900015
        # Expected penalty at 4.5 heat:
        # thd: 15 + (int(4.5)*10) = 15 + 40 = 55
        # noise_floor: 90 - int(4.5) = 90 - 4 = 86
        self.write_dna(["CLAZN0900015"])
        dna_main(data_dir=self.data_dir)

        with open(os.path.join(self.out_dir, 'toSequence_parsed.json'), 'r') as f:
            results = json.load(f)
            cla_result = next(r for r in results if r['dna'] == "CLAZN0900015")
            self.assertEqual(cla_result['parsed']['thd'], 55)
            self.assertEqual(cla_result['parsed']['noise_floor']['value'], 86)

    def test_thermal_refusal_not_persistent_in_ledger(self):
        # Heat to 11.0 (exceeds 10.0 threshold)
        # VOL11500000000 -> +11.5 heat. Batch end -> 11.0.
        self.write_dna(["VOL11500000000"])
        dna_main(data_dir=self.data_dir)
        self.assertEqual(self.get_heat(), 11.0)

        # Next batch should be refused
        dna_refused = "VOL01000000000"
        self.write_dna([dna_refused])
        dna_main(data_dir=self.data_dir)

        # Ledger should NOT contain the refused DNA so it can be retried later
        if os.path.exists(self.ledger_file):
            with open(self.ledger_file, 'r') as f:
                ledger = json.load(f)
                self.assertNotIn(dna_refused, ledger)

        # Heat should still dissipate even on refusal
        # 11.0 - 0.5 = 10.5
        self.assertEqual(self.get_heat(), 10.5)

    def test_idempotency_no_double_heat(self):
        # Process same VOL string twice in different batches
        self.write_dna(["VOL02000000000"])
        dna_main(data_dir=self.data_dir)
        heat1 = self.get_heat() # 2.0 - 0.5 = 1.5
        self.assertEqual(heat1, 1.5)

        # Second time - should be skipped by idempotency
        self.write_dna(["VOL02000000000"])
        dna_main(data_dir=self.data_dir)
        heat2 = self.get_heat() # 1.5 - 0.5 = 1.0 (only dissipation)
        self.assertEqual(heat2, 1.0)

if __name__ == '__main__':
    unittest.main()

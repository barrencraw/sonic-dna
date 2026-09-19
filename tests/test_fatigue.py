import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class TestFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        # Mock a valid rule file (Volume prefix V)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_ui_message_keys(self):
        err = ThermalOverloadError(current_heat=11.0, max_heat=10.0)
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

    def test_heat_accumulation_and_idempotency_exactly_once(self):
        # Write 2 DNA strings (each adds 2.0 heat => total 4.0 heat)
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\n")

        run_batch()

        ledger, state = load_ledger(self.ledger_file)
        self.assertIn("V100", ledger)
        self.assertIn("V200", ledger)
        self.assertEqual(state['core_heat'], 4.0)

        # Re-run same batch (idempotency deduplication)
        # Should not process new items and should NOT accumulate additional heat
        run_batch()

        _, state_after = load_ledger(self.ledger_file)
        self.assertAlmostEqual(state_after['core_heat'], 4.0, places=1)

    def test_thermal_lockout_no_silent_drains(self):
        # Max heat is 10.0. Each item adds 2.0 heat.
        # Submitting 6 distinct items requires 12.0 heat, which exceeds 10.0.
        dna_items = [f"V00{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_items) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check that state was updated to reflect heat accumulated before lockout
        _, state = load_ledger(self.ledger_file)
        self.assertGreater(state['core_heat'], 0.0)

        # Verify input file is NOT silently drained or deleted
        with open(self.input_file, 'r') as f:
            remaining_content = f.read().strip()
        self.assertTrue(len(remaining_content) > 0)

if __name__ == '__main__':
    unittest.main()

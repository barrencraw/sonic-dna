import os
import json
import shutil
import unittest
import tempfile
import time
from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)


class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_dir, 'toSequence_parsed.json')

        # Mock a valid rule file (Volume prefix V)
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_thermal_fatigue_idempotency_and_no_silent_drains(self):
        # 1. Batch 1: Process 3 sequences (+6.0 heat units)
        with open(self.input_file, 'w') as f:
            f.write("V100\nV200\nV300\n")

        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)

        self.assertIn('system_state', ledger)
        self.assertAlmostEqual(ledger['system_state']['core_heat'], 6.0, delta=0.5)

        with open(self.json_output, 'r') as f:
            parsed_data = json.load(f)
        self.assertEqual(len(parsed_data), 3)

        # 2. Re-invocation with same sequences (Idempotency check)
        # Should deduplicate, add 0 core heat, and not duplicate parsed entries
        run_batch()

        with open(self.json_output, 'r') as f:
            parsed_data_retry = json.load(f)
        self.assertEqual(len(parsed_data_retry), 3, "Idempotency: duplicated inputs must not re-parse")

        # 3. Batch 2: Excess load attempt (+6.0 heat units on top of existing ~6.0 > 10.0 threshold)
        with open(self.input_file, 'w') as f:
            f.write("V400\nV500\nV600\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err_msg = str(cm.exception)
        # Verify UI message key constants and indifferent tone hint in refusal message
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # 4. No Silent Drains verification:
        # Output files must NOT contain the rejected items (V400, V500, V600)
        with open(self.json_output, 'r') as f:
            parsed_data_after_refusal = json.load(f)
        self.assertEqual(len(parsed_data_after_refusal), 3, "No silent drains: refused batch must not alter output files")

        # Thermal state in ledger must preserve current heat state and not be silently reset/drained
        with open(self.ledger_file, 'r') as f:
            ledger_after_refusal = json.load(f)
        self.assertAlmostEqual(ledger_after_refusal['system_state']['core_heat'], 6.0, delta=0.5)


if __name__ == '__main__':
    unittest.main()

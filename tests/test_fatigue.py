import os
import json
import time
import shutil
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    CONSEQUENCE_HEAT_ACCUMULATION,
    REFUSAL_THERMAL_LOCKOUT,
    HINT_WAIT_FOR_DISSIPATION,
    HEAT_PER_SEQUENCE,
    MAX_HEAT_THRESHOLD,
    COOLING_RATE_PER_SEC
)

class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock rule file for Volume ('VOL') prefix
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_idempotency_and_heat_accumulation(self):
        """
        Proof test:
        1. Newly processed sequences apply heat (+2.0 each) exactly once.
        2. Deduplicated (re-submitted) sequences apply 0 heat (idempotency).
        """
        dna_list = ["VOL00100000000", "VOL00200000000"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        # Initial run: t = 1000.0, 2 new sequences -> 2 * 2.0 = 4.0 heat
        with patch('time.time', return_value=1000.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)

        self.assertIn('_system_state', ledger)
        self.assertEqual(ledger['_system_state']['core_heat'], 4.0)
        self.assertEqual(len([k for k in ledger if k != '_system_state']), 2)

        # Re-submit exact same sequences immediately (t = 1000.0)
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_list) + "\n")

        with patch('time.time', return_value=1000.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_after = json.load(f)

        # Heat must remain 4.0 (no duplicate heat applied for deduplicated items)
        self.assertEqual(ledger_after['_system_state']['core_heat'], 4.0)

    def test_thermal_lockout_and_no_silent_drains(self):
        """
        Proof test:
        1. Exceeding heat threshold triggers ThermalOverloadError with explicit refusal keys.
        2. In main.py process_once, a ThermalOverloadError prevents input file truncation (no silent drains).
        """
        # 6 sequences * 2.0 heat = 12.0 heat > 10.0 threshold
        overload_dnas = [f"VOL00{i}00000000" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(overload_dnas) + "\n")

        # Directly testing run_batch raises ThermalOverloadError
        with patch('time.time', return_value=1000.0):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

        err = cm.exception
        self.assertEqual(err.message_key, REFUSAL_THERMAL_LOCKOUT)
        self.assertEqual(err.hint, HINT_WAIT_FOR_DISSIPATION)
        self.assertIn(REFUSAL_THERMAL_LOCKOUT, str(err))

        # Testing main.py process_once: run batch failure should NOT clear input file
        import main
        with open(self.input_file, 'w') as f:
            f.write("\n".join(overload_dnas) + "\n")

        with patch('time.time', return_value=1000.0):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file must still contain all unparsed sequences (no silent drains)
        with open(self.input_file, 'r') as f:
            remaining_content = f.read().strip().splitlines()
        self.assertGreater(len(remaining_content), 0, "Input file must not be silently drained on lockout")

    def test_deterministic_cooling_decay(self):
        """
        Proof test:
        Verify core heat decays deterministically over time at 0.5 units/sec.
        """
        dna = "VOL00100000000"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Run 1: t = 1000.0, core_heat becomes 2.0
        with patch('time.time', return_value=1000.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertEqual(ledger['_system_state']['core_heat'], 2.0)

        # Run 2: t = 1002.0 (2 seconds elapsed). Cooling: 2 * 0.5 = 1.0 heat dissipated.
        # Adding new sequence (+2.0): 2.0 - 1.0 + 2.0 = 3.0 core heat.
        new_dna = "VOL00200000000"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        with patch('time.time', return_value=1002.0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['_system_state']['core_heat'], 3.0)

if __name__ == '__main__':
    unittest.main()

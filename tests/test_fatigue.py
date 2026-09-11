import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_idempotency_does_not_accumulate_heat(self):
        """Proof: Re-processing identical DNA sequences (deduplicated) adds 0 heat units."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        ledger1 = load_ledger(self.ledger_path)
        heat1 = ledger1.get('system_state', {}).get('core_heat')
        self.assertEqual(heat1, 2.0, "Initial sequence processing must add exactly 2.0 heat units")

        # Second invocation with same DNA
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        ledger2 = load_ledger(self.ledger_path)
        heat2 = ledger2.get('system_state', {}).get('core_heat')
        self.assertEqual(heat2, 2.0, "Duplicate sequence hit must NOT accumulate heat")

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        """Proof: Excess burst triggers ThermalOverloadError and preserves system/watcher state with no silent drains."""
        # Write 6 unique sequences (6 * 2.0 = 12.0 heat > 10.0 threshold)
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check ledger state reflects thermal lockout state
        ledger = load_ledger(self.ledger_path)
        self.assertIn('system_state', ledger)
        self.assertGreater(ledger['system_state']['core_heat'], 0.0)

        # Verify input file content remains intact (no silent drains)
        with open(self.input_file, 'r') as f:
            raw_input = f.read().strip().splitlines()
        self.assertEqual(len(raw_input), 6, "Input file must NOT be cleared or drained on thermal refusal")

    def test_thermal_dissipation_over_time(self):
        """Proof: Waiting allows core heat to dissipate deterministically."""
        dnas = [f"VOL0890075071{i}" for i in range(5)] # 5 * 2.0 = 10.0 heat
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertEqual(ledger['system_state']['core_heat'], 10.0)

        # Simulate 10 seconds of elapsed time (10s * 0.5 heat/s = 5.0 heat dissipated)
        import datetime
        past_dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=10.0)
        past_time_str = past_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

        ledger['system_state']['last_processed_timestamp'] = past_time_str
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger, f)

        # Process new sequence
        new_dna = "VOL09900990999"
        with open(self.input_file, 'w') as f:
            f.write(new_dna + "\n")

        run_batch()

        new_ledger = load_ledger(self.ledger_path)
        # 10.0 - 5.0 (cooling) + 2.0 (new DNA) = 7.0 heat
        new_heat = new_ledger['system_state']['core_heat']
        self.assertAlmostEqual(new_heat, 7.0, delta=0.5)

if __name__ == '__main__':
    unittest.main()

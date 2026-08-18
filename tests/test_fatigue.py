import os
import json
import shutil
import unittest
import time
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger

class TestThermalFatigueSystem(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)
            shutil.rmtree(self.data_folder)

        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_idempotency_applied_exactly_once(self):
        """Verify heat is applied exactly once per unique DNA sequence; re-processing adds zero heat."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        # First run: processes 1 new sequence -> adds 2.0 heat
        run_batch()

        ledger = load_ledger(self.ledger_path)
        system_state = ledger.get('__system_state__', {})
        self.assertAlmostEqual(system_state.get('core_heat'), 2.0)
        self.assertIn(dna, ledger)

        # Second run: same sequence -> deduplication hit -> 0 additional heat
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        run_batch()

        ledger_after = load_ledger(self.ledger_path)
        system_state_after = ledger_after.get('__system_state__', {})
        # Heat should still be ~2.0 (minus any tiny sub-millisecond dissipation)
        self.assertAlmostEqual(system_state_after.get('core_heat'), 2.0, delta=0.1)

    def test_thermal_lockout_refusal_keys_and_no_silent_drains(self):
        """Verify refusal keys on overload and ensure input file is not silently drained."""
        # 6 unique DNA sequences * 2.0 heat = 12.0 heat (exceeds threshold 10.0)
        dnas = [f"VOL0890075071{i}" for i in range(6)]
        input_content = "\n".join(dnas) + "\n"

        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(input_content)

        # Attempt batch parse: should raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err = ctx.exception
        # Assert exact UI message keys
        self.assertEqual(err.consequence_applied, "Heat Accumulation")
        self.assertEqual(err.refusal_reason, "Thermal Lockout")
        self.assertEqual(err.next_action_hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Verify NO SILENT DRAINS: Input file is intact, no output JSON was generated
        with open(self.input_file, 'r', encoding='utf-8') as f:
            current_input = f.read()
        self.assertEqual(current_input, input_content, "Input file must remain intact when operation is refused.")

        self.assertFalse(os.path.exists(self.json_output), "No partial parsed output should be committed on refusal.")

    def test_thermal_dissipation_over_time(self):
        """Verify core heat dissipates at 0.5 units/second over time."""
        dna1 = "VOL08900750711"
        dna2 = "VOL08900750712"
        dna3 = "VOL08900750713"
        dna4 = "VOL08900750714"

        t0 = 1000.0
        with patch('time.time', return_value=t0):
            # Process 4 unique sequences -> 8.0 heat
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write(f"{dna1}\n{dna2}\n{dna3}\n{dna4}\n")
            run_batch()

        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger['__system_state__']['core_heat'], 8.0)

        # Fast forward time by 10 seconds (10s * 0.5 units/s = 5.0 units dissipated -> remaining heat = 3.0)
        t1 = t0 + 10.0
        dna5 = "VOL08900750715"
        with patch('time.time', return_value=t1):
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write(f"{dna5}\n")
            run_batch()

        ledger_after = load_ledger(self.ledger_path)
        # 3.0 remaining + 2.0 new sequence = 5.0 heat
        self.assertAlmostEqual(ledger_after['__system_state__']['core_heat'], 5.0)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import time
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    calculate_current_heat,
    HEAT_PER_PARSE,
    LOCKOUT_THRESHOLD,
    COOLING_RATE_PER_SEC,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT
)

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

    def test_deterministic_cooling_calculation(self):
        """Test passive dissipation of core heat over elapsed time."""
        initial_heat = 8.0
        t0 = 1000.0

        # After 4 seconds at 0.5 units/sec dissipation, heat should be 8.0 - 2.0 = 6.0
        t1 = 1004.0
        heat_t1 = calculate_current_heat(initial_heat, t0, t1)
        self.assertAlmostEqual(heat_t1, 6.0)

        # After 20 seconds, heat cannot drop below 0.0
        t2 = 1020.0
        heat_t2 = calculate_current_heat(initial_heat, t0, t2)
        self.assertEqual(heat_t2, 0.0)

    def test_heat_accumulation_and_idempotency_without_leak(self):
        """
        Test that each newly processed DNA adds exact heat (HEAT_PER_PARSE),
        while deduplicated invocations (idempotency hits) do NOT accumulate heat.
        """
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # 1. First invocation: parses 1 item -> heat increases by HEAT_PER_PARSE
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertEqual(ledger_data['system_state']['core_heat'], HEAT_PER_PARSE)

        # 2. Second invocation with same DNA (idempotent dedupe) at nearly the same instant:
        # Must not add heat again (exact once application).
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        # Mock time so no cooling occurs between runs
        now_ts = ledger_data['system_state']['last_processed_timestamp']
        with patch('time.time', return_value=now_ts):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data2 = json.load(f)

        self.assertEqual(
            ledger_data2['system_state']['core_heat'],
            HEAT_PER_PARSE,
            "Duplicate invocation should not add heat units to core"
        )

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        """
        Test that exceeding LOCKOUT_THRESHOLD triggers refusal with appropriate message keys
        and that un-processed queue is preserved without silent loss or drains.
        """
        # LOCKOUT_THRESHOLD is 10.0, each parse adds 2.0.
        # Generating 6 sequences (needs 12.0 heat units) to exceed threshold.
        dnas = [
            f"VOL{str(i).zfill(3)}00750712" for i in range(1, 7)
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        # Running batch should raise ThermalOverloadError when exceeding threshold
        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err_msg = str(ctx.exception)
        # Verify legibility pass message keys are present in refusal
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Verify no silent drains:
        # File still contains the sequences (caller/watcher will not clear input_file on ThermalOverloadError)
        with open(self.input_file, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
        self.assertEqual(lines, dnas, "Queue in toSequence.txt must not be silently drained or lost")

        # Verify state in ledger recorded lockout heat level
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        self.assertGreaterEqual(ledger_data['system_state']['core_heat'], LOCKOUT_THRESHOLD)

if __name__ == '__main__':
    unittest.main()

import os
import json
import shutil
import unittest
import time
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    MAX_CORE_HEAT,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC,
    MSG_CONSEQUENCE_APPLIED,
    MSG_REFUSAL_REASON,
    MSG_NEXT_ACTION_HINT,
    calculate_current_heat
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
        self.csv_output = os.path.join(self.output_folder, 'toSequence_parsed.csv')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
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

    def test_heat_accumulation_and_state_persistence(self):
        """Sequences parsed increase core heat deterministically by HEAT_PER_SEQUENCE."""
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)

        self.assertIn('system_state', ledger_data)
        self.assertEqual(ledger_data['system_state']['core_heat'], HEAT_PER_SEQUENCE)

    def test_deterministic_cooling_dissipation(self):
        """Core heat dissipates deterministically over elapsed time."""
        initial_heat = 6.0
        start_ts = 1000.0

        # After 4 seconds at 0.5 units/sec, heat drops by 2.0 -> 4.0
        cooled_heat = calculate_current_heat(initial_heat, start_ts, current_timestamp=1004.0)
        self.assertEqual(cooled_heat, 4.0)

        # After 20 seconds, heat floor is 0.0
        cooled_heat_min = calculate_current_heat(initial_heat, start_ts, current_timestamp=1020.0)
        self.assertEqual(cooled_heat_min, 0.0)

    def test_idempotency_double_invocation_zero_heat(self):
        """
        Double invocation / deduplicated entries must be applied exactly once:
        no duplicate side-effects and zero additional heat accumulation.
        """
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        t0 = 1000.0
        with patch('time.time', return_value=t0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data_first = json.load(f)
        self.assertEqual(data_first['system_state']['core_heat'], HEAT_PER_SEQUENCE)

        # Second run immediately with same sequence (deduplicated)
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('time.time', return_value=t0):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            data_second = json.load(f)

        # Heat should NOT have increased because the item was already in ledger
        self.assertEqual(data_second['system_state']['core_heat'], HEAT_PER_SEQUENCE)

    def test_thermal_lockout_refusal_and_no_silent_drains(self):
        """
        Exceeding MAX_CORE_HEAT raises ThermalOverloadError.
        No silent drains: unprocessed/refused items halt processing and trigger exception.
        Legibility: UI message keys for refusal reason and indifferent hint are surfaced.
        """
        # MAX_CORE_HEAT = 10.0, HEAT_PER_SEQUENCE = 2.0
        # 5 items = 10.0 heat. 6th item would be 12.0 heat -> exceeds 10.0
        dnas = [
            "VOL00000000001",
            "VOL00000000002",
            "VOL00000000003",
            "VOL00000000004",
            "VOL00000000005",
            "VOL00000000006"
        ]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(dnas) + "\n")

        t0 = 2000.0
        with patch('time.time', return_value=t0):
            with self.assertRaises(ThermalOverloadError) as ctx:
                run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Verify that atomic commit recorded exactly 5 processed sequences and didn't lose them
        with open(self.json_output, 'r') as f:
            parsed = json.load(f)
        self.assertEqual(len(parsed), 5)

        # The 6th item was not silently drained or marked success
        with open(self.ledger_path, 'r') as f:
            ledger_data = json.load(f)
        ledger = ledger_data.get('ledger', ledger_data)
        self.assertNotIn("VOL00000000006", ledger)
        self.assertEqual(ledger_data['system_state']['core_heat'], 10.0)

    def test_watcher_no_silent_queue_drain_on_lockout(self):
        """
        In main.py watcher loop, when ThermalOverloadError is raised,
        toSequence.txt is NOT cleared so queue items are not silently discarded.
        """
        # Force reload main
        import sys
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        # Create input file with DNA
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna}\n")

        with patch('main.__file__', os.path.join(self.project_root, 'main.py')):
            with patch('main.run_batch', side_effect=ThermalOverloadError("Thermal Lockout")):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()

                    # Input file was NOT cleared
                    mock_clear.assert_not_called()

        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read().strip(), dna)

if __name__ == '__main__':
    unittest.main()

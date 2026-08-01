import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch
from utils.dna_ui import main as run_batch, ThermalOverloadError, load_ledger, save_ledger

class TestFatigue(unittest.TestCase):
    def setUp(self):
        # Setup paths
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

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty structured ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({
                "system_heat": 0.0,
                "last_processed_time": None,
                "ledger": {}
            }, f)

        # Setup MockDatetime to test time-based dissipation deterministically
        self.mock_now = datetime.datetime(2025, 6, 15, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime:
            timezone = datetime.timezone
            class datetime:
                _now_val = self.mock_now
                @classmethod
                def now(cls, tz=None):
                    return cls._now_val
                @classmethod
                def strptime(cls, s, f):
                    return datetime.datetime.strptime(s, f)

        self.mock_dt_class = MockDatetime
        self.dt_patcher = patch('utils.dna_ui.datetime', MockDatetime)
        self.dt_patcher.start()

    def tearDown(self):
        self.dt_patcher.stop()
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_heat_accumulation_per_sequence(self):
        # 1. Prepare one DNA sequence
        dna1 = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna1 + "\n")

        # 2. Run batch
        run_batch()

        # 3. Verify heat accumulated (2.0 per sequence)
        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 2.0)

        # 4. Prepare another DNA sequence
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna2 + "\n")

        # 5. Run batch again
        run_batch()

        # 6. Verify heat increased to 4.0
        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 4.0)

    def test_heat_dissipation_over_time(self):
        # 1. Process 2 sequences to accumulate 4.0 heat
        dna1 = "VOL08900750712"
        dna2 = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(f"{dna1}\n{dna2}\n")

        run_batch()

        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 4.0)

        # 2. Advance mocked time by 4.0 seconds (4.0 * 0.5 = 2.0 units of cooling)
        self.mock_dt_class.datetime._now_val += datetime.timedelta(seconds=4)

        # 3. Run batch with no new elements to record cooling
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        # 4. Verify system heat cooled down to 2.0
        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 2.0)

    def test_thermal_lockout_prevents_processing(self):
        # 1. Process 5 sequences to reach 10.0 heat (lockout threshold)
        dna_sequences = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL10000000000",
            "VOL20000000000",
            "VOL30000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        # Running this should raise ThermalOverloadError because the 5th sequence pushes heat to 10.0, triggering immediate overload
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check ledger has 10.0 heat
        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 10.0)

        # 2. Attempt to process another sequence when locked out should be immediately refused
        dna_new = "VOL40000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna_new + "\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Thermal Lockout", str(context.exception))
        self.assertIn("Wait for dissipation", str(context.exception))

        # Verify that the sequence was NOT processed or added to the output files/ledger
        ledger_data = load_ledger(self.ledger_path)
        self.assertNotIn(dna_new, ledger_data["ledger"])

    def test_partial_results_committed_before_lockout(self):
        # 1. Have 6 new sequences in the input file
        dna_sequences = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL10000000000",
            "VOL20000000000",
            "VOL30000000000",
            "VOL40000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        # 2. Run the batch, expecting it to process 5 sequences and then raise ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # 3. Verify that the first 5 sequences are committed to output and ledger, but NOT the 6th
        with open(self.json_output, 'r') as f:
            parsed_data = json.load(f)

        self.assertEqual(len(parsed_data), 5)
        processed_dnas = [entry['dna_sequence'] for entry in parsed_data]
        for dna in dna_sequences[:5]:
            self.assertIn(dna, processed_dnas)
        self.assertNotIn(dna_sequences[5], processed_dnas)

        ledger_data = load_ledger(self.ledger_path)
        for dna in dna_sequences[:5]:
            self.assertIn(dna, ledger_data["ledger"])
            self.assertEqual(ledger_data["ledger"][dna]["terminal_outcome"], "success")
        self.assertNotIn(dna_sequences[5], ledger_data["ledger"])

    def test_thermal_debt_force_override(self):
        # 1. Cause thermal lockout by processing 5 sequences (accumulating 10.0 heat)
        dna_sequences = [
            "VOL08900750712",
            "VOL00000000000",
            "VOL10000000000",
            "VOL20000000000",
            "VOL30000000000"
        ]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 10.0)
        self.assertAlmostEqual(ledger_data.get("system_debt", 0.0), 0.0)

        # 2. Try to process a new sequence normal - should be locked out
        with open(self.input_file, 'w') as f:
            f.write("VOL40000000000\n")
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # 3. Try to process with FORCE_OVERRIDE directive - should bypass lockout!
        with open(self.input_file, 'w') as f:
            f.write("VOL40000000000\nFORCE_OVERRIDE\n")

        run_batch()

        # 4. Verify sequence processed and debt accumulated to 2.0, threshold reduced to 8.0
        ledger_data = load_ledger(self.ledger_path)
        self.assertIn("VOL40000000000", ledger_data["ledger"])
        self.assertAlmostEqual(ledger_data.get("system_debt", 0.0), 2.0)
        # Heat should be 10.0 (prev) + 2.0 (processed sequence) = 12.0
        self.assertAlmostEqual(ledger_data["system_heat"], 12.0)

    def test_core_exhaustion_at_max_debt(self):
        # 1. Directly inject 10.0 system_debt to simulate max wear
        ledger_data = load_ledger(self.ledger_path)
        ledger_data["system_debt"] = 10.0
        save_ledger(self.ledger_path, ledger_data)

        # 2. Attempt to process with override - should be flatly refused with Core Exhaustion
        with open(self.input_file, 'w') as f:
            f.write("VOL08900750712\nFORCE_OVERRIDE\n")

        with self.assertRaises(ThermalOverloadError) as context:
            run_batch()

        self.assertIn("Core Exhaustion", str(context.exception))
        self.assertIn("idle cooling", str(context.exception))

    def test_debt_and_heat_idle_dissipation(self):
        # 1. Inject 4.0 heat and 2.0 debt
        ledger_data = load_ledger(self.ledger_path)
        ledger_data["system_heat"] = 4.0
        ledger_data["system_debt"] = 2.0
        ledger_data["last_processed_time"] = self.mock_now.strftime('%Y-%m-%dT%H:%M:%SZ')
        save_ledger(self.ledger_path, ledger_data)

        # 2. Cool down by 10.0 seconds
        # Dissipation capacity: 10.0 * 0.5 = 5.0 heat.
        # It takes 4.0 / 0.5 = 8.0 seconds to dissipate heat to 0.0.
        # This leaves 2.0 seconds of remaining time.
        # Remaining time reduces debt: 2.0 * 0.1 = 0.2 units.
        self.mock_dt_class.datetime._now_val += datetime.timedelta(seconds=10)

        # Run batch with no new entries to trigger cooling
        with open(self.input_file, 'w') as f:
            f.write("")

        run_batch()

        # Verify heat is 0.0, debt is 1.8
        ledger_data = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger_data["system_heat"], 0.0)
        self.assertAlmostEqual(ledger_data.get("system_debt", 0.0), 1.8)

if __name__ == '__main__':
    unittest.main()

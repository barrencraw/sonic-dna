import os
import json
import shutil
import tempfile
import unittest
import datetime as real_datetime
from unittest.mock import patch

from utils.dna_ui import (
    main as run_batch,
    load_ledger,
    save_ledger,
    ThermalOverloadError,
    THERMAL_MESSAGE_KEYS,
    HEAT_PER_SEQUENCE,
    COOLING_RATE_PER_SEC,
    THERMAL_LOCKOUT_THRESHOLD
)

class MockDatetime(real_datetime.datetime):
    _mock_now = None

    @classmethod
    def now(cls, tz=None):
        if cls._mock_now is not None:
            return cls._mock_now
        return real_datetime.datetime.now(tz)

class MockDatetimeModule:
    datetime = MockDatetime
    timezone = real_datetime.timezone

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

        # Mock a valid rule file (Volume prefix VOL)
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3},
                    "pan": {"description": "panning", "min": 0, "max": 999, "pad": 3},
                    "fade": {"description": "fade", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_heat_accumulation_and_idempotency(self):
        # VOL + 3 digits level + 3 digits pan + 3 digits fade = 12 chars
        seq1 = "VOL089007507"
        seq2 = "VOL000000000"

        fixed_t0 = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        MockDatetime._mock_now = fixed_t0

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            # 1. First run with 2 distinct sequences
            with open(self.input_file, 'w') as f:
                f.write(f"{seq1}\n{seq2}\n")

            run_batch()

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(len(ledger), 2)
            # 2 sequences * 2.0 heat = 4.0 heat
            self.assertAlmostEqual(system_state["core_heat"], 4.0, delta=0.01)

            # 2. Second run with same sequences (Idempotent: duplicate processing)
            with open(self.input_file, 'w') as f:
                f.write(f"{seq1}\n{seq2}\n")

            run_batch()

            ledger, system_state = load_ledger(self.ledger_path)
            self.assertEqual(len(ledger), 2)
            # Deduplicated runs add 0 heat
            self.assertAlmostEqual(system_state["core_heat"], 4.0, delta=0.01)

    def test_thermal_lockout_refusal_and_message_keys(self):
        fixed_t0 = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        MockDatetime._mock_now = fixed_t0

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            # Create a batch of 5 new valid sequences (5 * 2.0 = 10.0 heat -> hits lockout threshold)
            sequences = [f"VOL00000000{i}" for i in range(5)] # 12 char valid VOL sequences
            with open(self.input_file, 'w') as f:
                f.write("\n".join(sequences) + "\n")

            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

            err = cm.exception
            self.assertEqual(err.consequence, THERMAL_MESSAGE_KEYS["consequence_applied"])
            self.assertEqual(err.reason, THERMAL_MESSAGE_KEYS["refusal_reason"])
            self.assertEqual(err.hint, THERMAL_MESSAGE_KEYS["next_action_hint"])

            # Check ledger system_state heat is saved accurately when refused
            ledger, system_state = load_ledger(self.ledger_path)
            self.assertGreaterEqual(system_state["core_heat"], 8.0) # 4 sequences processed (8.0 heat) before 5th was refused

    def test_thermal_dissipation(self):
        # Pre-set system state with 8.0 heat at T0
        t0 = real_datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=real_datetime.timezone.utc)
        system_state = {
            "core_heat": 8.0,
            "last_processed_timestamp": t0.strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        save_ledger(self.ledger_path, {}, system_state)

        # 10 seconds pass -> 10 * 0.5 = 5.0 heat dissipated -> remaining heat = 3.0
        t1 = t0 + real_datetime.timedelta(seconds=10)

        MockDatetime._mock_now = t1

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            with open(self.input_file, 'w') as f:
                f.write("VOL089007507\n") # Adds 2.0 heat -> total heat becomes 3.0 + 2.0 = 5.0

            run_batch()

            ledger, updated_system_state = load_ledger(self.ledger_path)
            self.assertAlmostEqual(updated_system_state["core_heat"], 5.0, delta=0.01)

if __name__ == '__main__':
    unittest.main()

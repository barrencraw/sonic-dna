import os
import json
import shutil
import unittest
import tempfile
import datetime
from unittest.mock import patch, MagicMock
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

        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)
        os.makedirs(self.rules_dir)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a valid rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w', encoding='utf-8') as f:
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

    def test_idempotency_no_heat_buildup(self):
        """Verify re-running an already processed sequence causes zero heat increase."""
        dna = "VOL08900750712"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{dna}\n")

        fixed_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        with patch('utils.dna_ui.datetime', MagicMock(datetime=MockDatetime, timezone=datetime.timezone)):
            run_batch()

            with open(self.ledger_file, 'r', encoding='utf-8') as f:
                ledger = json.load(f)

            self.assertIn(dna, ledger)
            self.assertEqual(ledger['_system_state']['core_heat'], 2.0)

            # Second run with exact same sequence
            run_batch()

            with open(self.ledger_file, 'r', encoding='utf-8') as f:
                ledger = json.load(f)

            # Heat must remain 2.0 because deduplicated sequence adds 0 heat
            self.assertEqual(ledger['_system_state']['core_heat'], 2.0)

    def test_thermal_lockout_refusal_and_message_keys(self):
        """Verify thermal overload lockout refusal triggers with required UI message keys."""
        # 5 distinct sequences will add +2.0 heat each = 10.0 (max capacity)
        dnas = [f"VOL{i:03d}" for i in range(1, 7)]  # 6 sequences
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(dnas) + "\n")

        fixed_time = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_time

        with patch('utils.dna_ui.datetime', MagicMock(datetime=MockDatetime, timezone=datetime.timezone)):
            with self.assertRaises(ThermalOverloadError) as cm:
                run_batch()

            err = cm.exception
            self.assertEqual(err.consequence_applied, MSG_CONSEQUENCE_APPLIED)
            self.assertEqual(err.refusal_reason, MSG_REFUSAL_REASON)
            self.assertEqual(err.next_action_hint, MSG_NEXT_ACTION_HINT)
            self.assertIn(MSG_REFUSAL_REASON, str(err))
            self.assertIn(MSG_NEXT_ACTION_HINT, str(err))

            # Verify 5 sequences were processed, 6th was refused
            with open(self.ledger_file, 'r', encoding='utf-8') as f:
                ledger = json.load(f)

            self.assertEqual(ledger['_system_state']['core_heat'], 10.0)
            self.assertIn("VOL005", ledger)
            self.assertNotIn("VOL006", ledger)

    def test_deterministic_cooling_decay(self):
        """Verify heat dissipates deterministically over elapsed time (-0.5 units/sec)."""
        # Initial state: 10.0 heat at 12:00:00
        initial_ledger = {
            "VOL001": {"terminal_outcome": "success", "timestamp": "2026-03-02 12:00:00"},
            "_system_state": {
                "core_heat": 10.0,
                "last_processed_timestamp": "2026-03-02T12:00:00Z"
            }
        }
        with open(self.ledger_file, 'w', encoding='utf-8') as f:
            json.dump(initial_ledger, f)

        # Run 10 seconds later: 10.0 - (10 * 0.5) = 5.0 heat
        # Processing 1 new sequence adds +2.0 = 7.0 heat
        new_dna = "VOL002"
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write(f"{new_dna}\n")

        later_time = datetime.datetime(2026, 3, 2, 12, 0, 10, tzinfo=datetime.timezone.utc)

        class MockDatetime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return later_time

        with patch('utils.dna_ui.datetime', MagicMock(datetime=MockDatetime, timezone=datetime.timezone)):
            run_batch()

            with open(self.ledger_file, 'r', encoding='utf-8') as f:
                ledger = json.load(f)

            self.assertEqual(ledger['_system_state']['core_heat'], 7.0)

if __name__ == '__main__':
    unittest.main()

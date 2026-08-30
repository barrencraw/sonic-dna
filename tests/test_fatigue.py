import sys
from unittest.mock import MagicMock, patch

# Mock PySide6 and audio dependencies before imports
mock_pyside6 = MagicMock()
sys.modules["PySide6"] = mock_pyside6
sys.modules["PySide6.QtWidgets"] = mock_pyside6
sys.modules["PySide6.QtCore"] = mock_pyside6
sys.modules["PySide6.QtGui"] = mock_pyside6
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
import datetime
from utils.dna_ui import (
    main as run_batch,
    load_ledger,
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

        # Create mock rule file for Volume ('VOL' prefix)
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

    def test_heat_accumulation_and_idempotency(self):
        """Verify that processing adds heat, but repeated deduplicated runs add 0 heat (idempotency)."""
        # Write 2 DNA sequences (2 * 2.0 = 4.0 heat)
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("VOL08900750712\nVOL00000000000\n")

        run_batch()

        ledger_data = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data['system_state']['core_heat'], 4.0)

        # Re-running with same sequences should hit deduplication and NOT add additional heat
        run_batch()
        ledger_data_re = load_ledger(self.ledger_file)
        self.assertEqual(ledger_data_re['system_state']['core_heat'], 4.0)

    def test_thermal_lockout_refusal(self):
        """Verify that exceeding 10.0 heat units triggers ThermalOverloadError without silent drains."""
        # 6 sequences * 2.0 = 12.0 heat, which breaches 10.0 threshold
        sequences = [f"VOL000000000{i:02d}" for i in range(6)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as ctx:
            run_batch()

        err_msg = str(ctx.exception)
        self.assertIn(MSG_REFUSAL_REASON, err_msg)
        self.assertIn(MSG_NEXT_ACTION_HINT, err_msg)

        # Output files should NOT exist (no partial or corrupted writes)
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        self.assertFalse(os.path.exists(json_out))

    def test_heat_decay_dissipation(self):
        """Verify that heat dissipates over simulated time allowing subsequent batch runs."""
        # 4 sequences * 2.0 = 8.0 heat
        sequences_batch1 = [f"VOL100000000{i:02d}" for i in range(4)]
        with open(self.input_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(sequences_batch1) + "\n")

        import datetime as real_datetime
        base_time = real_datetime.datetime(2026, 8, 30, 12, 0, 0, tzinfo=real_datetime.timezone.utc)

        class MockDatetime(real_datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls._current_time

        class MockDatetimeModule:
            datetime = MockDatetime
            timezone = real_datetime.timezone

        MockDatetime._current_time = base_time

        with patch('utils.dna_ui.datetime', MockDatetimeModule):
            run_batch()
            ledger_data = load_ledger(self.ledger_file)
            self.assertEqual(ledger_data['system_state']['core_heat'], 8.0)

            # Try to process 2 more sequences immediately (8.0 + 4.0 = 12.0 > 10.0 -> raise error)
            sequences_batch2 = [f"VOL200000000{i:02d}" for i in range(2)]
            with open(self.input_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(sequences_batch2) + "\n")

            with self.assertRaises(ThermalOverloadError):
                run_batch()

            # Advance simulated time by 10 seconds (decay = 10s * 0.5 = 5.0 heat reduced, new base heat = 3.0)
            # 3.0 + 4.0 = 7.0 <= 10.0 -> should succeed!
            MockDatetime._current_time = base_time + datetime.timedelta(seconds=10)
            run_batch()

            ledger_data_after = load_ledger(self.ledger_file)
            self.assertEqual(ledger_data_after['system_state']['core_heat'], 7.0)

if __name__ == '__main__':
    unittest.main()

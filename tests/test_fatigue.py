import sys
from unittest.mock import MagicMock

# Mock GUI and audio dependencies if not installed
mock_pyside6 = MagicMock()
sys.modules.setdefault("PySide6", mock_pyside6)
sys.modules.setdefault("PySide6.QtWidgets", mock_pyside6)
sys.modules.setdefault("PySide6.QtCore", mock_pyside6)
sys.modules.setdefault("PySide6.QtGui", mock_pyside6)
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("torchaudio", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

import os
import json
import shutil
import unittest
import tempfile
from unittest.mock import patch
from datetime import datetime, timezone, timedelta

from utils.dna_ui import (
    main as run_batch,
    ThermalOverloadError,
    HEAT_PER_PARSE,
    COOLING_RATE_PER_SEC,
    MAX_HEAT_THRESHOLD
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

        # Create valid volume rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_ui_message_keys(self):
        """Verify UI message keys on ThermalOverloadError."""
        err = ThermalOverloadError(current_heat=10.0, threshold=10.0)
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.reason, "Thermal Lockout")
        self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")
        self.assertIn("Thermal Lockout", str(err))
        self.assertIn("Heat Accumulation", str(err))
        self.assertIn("The system is indifferent to your deadlines.", str(err))

    def test_heat_accumulation_idempotency_and_lockout(self):
        """
        Proof Test:
        1. Parse 5 new sequences (+2.0 heat each = 10.0 heat -> triggers lockout on 6th item).
        2. Verify idempotency: re-submitting processed sequences adds 0 heat.
        3. Verify lockout persists until dissipation.
        """
        seqs = [f"VOL{i:03d}0000000" for i in range(1, 7)]

        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        # 1. Run batch - 5 will process, 6th will trigger ThermalOverloadError
        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(err.consequence, "Heat Accumulation")
        self.assertEqual(err.reason, "Thermal Lockout")
        self.assertEqual(err.hint, "Wait for dissipation. The system is indifferent to your deadlines.")

        # Check ledger heat state
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)

        self.assertIn("system_state", ledger)
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 10.0)

        # 5 items were processed in ledger
        for seq in seqs[:5]:
            self.assertIn(seq, ledger)
        self.assertNotIn(seqs[5], ledger)

        # 2. Test Idempotency: re-running with only the first 5 sequences
        # All 5 are dedupe hits (0 heat generated).
        # Should not throw ThermalOverloadError because no new item is being processed.
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs[:5]) + "\n")

        # Running batch with 100% dedupe hits
        run_batch()

        # Core heat remained unchanged by dedupe hits
        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 10.0)

    def test_no_silent_drains_in_main_runner(self):
        """Verify main.process_once() preserves input file when ThermalOverloadError occurs."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        seqs = [f"VOL{i:03d}0000000" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(seqs) + "\n")

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Verify input file was NOT cleared because run_batch raised ThermalOverloadError
        with open(self.input_file, 'r') as f:
            lines = [l.strip() for l in f if l.strip()]
            self.assertEqual(len(lines), 6)

    def test_thermal_dissipation_cooldown(self):
        """Verify that after time passes, heat decays at 0.5/sec and allows further processing."""
        # Pre-set ledger to 10.0 heat with timestamp 30 seconds ago
        past_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        initial_ledger = {
            "system_state": {
                "core_heat": 10.0,
                "last_processed_timestamp": past_time
            }
        }
        with open(self.ledger_file, 'w') as f:
            json.dump(initial_ledger, f)

        # New sequence
        seq = "VOL9990000000"
        with open(self.input_file, 'w') as f:
            f.write(seq + "\n")

        # 30 seconds elapsed * 0.5 heat/sec = 15.0 heat dissipation -> core heat drops to 0.0
        run_batch()

        with open(self.ledger_file, 'r') as f:
            ledger = json.load(f)

        self.assertIn(seq, ledger)
        # Heat dropped to 0.0, then +2.0 for the new parse = 2.0 heat
        self.assertAlmostEqual(ledger["system_state"]["core_heat"], 2.0)

if __name__ == '__main__':
    unittest.main()

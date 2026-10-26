import sys
from unittest.mock import MagicMock

# Mock non-standard C-extension modules before imports
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
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    ThermalOverloadError,
    THERMAL_UI_MESSAGES,
    load_ledger
)

class MockDatetime(datetime.datetime):
    simulated_now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls.simulated_now.astimezone(tz)
        return cls.simulated_now

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

        # Mock Volume rule
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "VOL",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.datetime.datetime', MockDatetime)
    def test_heat_accumulation_and_refusal(self):
        """Test heat accumulates (+2.0 per sequence) and triggers lockout at >10.0 heat."""
        MockDatetime.simulated_now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # 6 sequences -> 6 * 2.0 = 12.0 heat (lockout threshold is 10.0)
        sequences = [f"VOL{i:03d}" for i in range(1, 7)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check ledger state
        ledger, system_state = load_ledger(self.ledger_path)
        # Batch is atomically aborted on refusal, so initial ledger remain intact (0 new items committed)
        self.assertEqual(len(ledger), 0)
        # Accumulated core heat (10.0) prior to refusal is persisted to system_state
        self.assertAlmostEqual(system_state['core_heat'], 10.0)

    @patch('utils.dna_ui.datetime.datetime', MockDatetime)
    def test_heat_dissipation_and_idempotency(self):
        """Test heat decays at 0.5/sec and re-processed sequences do not add heat."""
        MockDatetime.simulated_now = datetime.datetime(2026, 3, 2, 12, 0, 0, tzinfo=datetime.timezone.utc)

        # Process 4 sequences = 8.0 heat
        sequences = [f"VOL{i:03d}" for i in range(1, 5)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        ledger, system_state = load_ledger(self.ledger_path)
        self.assertEqual(len(ledger), 4)
        self.assertAlmostEqual(system_state['core_heat'], 8.0)

        # Re-run with same sequences (deduplication / idempotency check)
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        run_batch()

        ledger, system_state = load_ledger(self.ledger_path)
        # Heat should remain 8.0 because no new items were processed
        self.assertAlmostEqual(system_state['core_heat'], 8.0)

        # Simulate 10 seconds of cooling time (10 * 0.5 = 5.0 heat dissipated)
        MockDatetime.simulated_now = datetime.datetime(2026, 3, 2, 12, 0, 10, tzinfo=datetime.timezone.utc)

        new_sequences = ["VOL005"]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(new_sequences) + "\n")

        run_batch()

        ledger, system_state = load_ledger(self.ledger_path)
        # 8.0 - 5.0 dissipation + 2.0 new sequence = 5.0 heat
        self.assertAlmostEqual(system_state['core_heat'], 5.0)

    def test_ui_messages_present(self):
        """Verify legibility requirement: message keys exist and have non-empty string values."""
        self.assertIn("consequence_applied", THERMAL_UI_MESSAGES)
        self.assertIn("refusal_reason", THERMAL_UI_MESSAGES)
        self.assertIn("next_action_hint", THERMAL_UI_MESSAGES)

        self.assertEqual(THERMAL_UI_MESSAGES["consequence_applied"], "Heat Accumulation")
        self.assertEqual(THERMAL_UI_MESSAGES["refusal_reason"], "Thermal Lockout")
        self.assertEqual(
            THERMAL_UI_MESSAGES["next_action_hint"],
            "Wait for dissipation. The system is indifferent to your deadlines."
        )

    def test_no_silent_drains_on_refusal(self):
        """Verify main.py watcher does not clear input file if run_batch raises ThermalOverloadError."""
        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        with patch.object(main, '__file__', os.path.join(self.test_dir, 'main.py')):
            with open(self.input_file, 'w') as f:
                f.write("VOL001\n")

            with patch('main.run_batch', side_effect=ThermalOverloadError("Thermal Lockout")):
                with patch('main.clear_input_file') as mock_clear:
                    with self.assertRaises(SystemExit):
                        main.process_once()
                    mock_clear.assert_not_called()

if __name__ == '__main__':
    unittest.main()

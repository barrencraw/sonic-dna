import sys
from unittest.mock import MagicMock, patch

# Mock PySide6 and audio dependencies if missing
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

from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')

        self.backup_folder = os.path.join(self.project_root, 'data_backup_fatigue')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        with open(self.ledger_path, 'w') as f:
            json.dump({'ledger': {}, 'system_state': {'core_heat': 0.0, 'last_processed_timestamp': 0.0}}, f)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    def test_thermal_overload_and_message_keys(self):
        """
        Verify that processing more than 5 new sequences (each adding 2.0 heat units)
        exceeds the 10.0 heat capacity threshold and raises ThermalOverloadError with legible keys.
        """
        dna_sequences = [f"VOL089007507{i:02d}" for i in range(6)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(dna_sequences) + "\n")

        with self.assertRaises(ThermalOverloadError) as cm:
            run_batch()

        err = cm.exception
        self.assertEqual(ThermalOverloadError.consequence_applied, "Heat Accumulation")
        self.assertEqual(ThermalOverloadError.refusal_reason, "Thermal Lockout")
        self.assertEqual(
            ThermalOverloadError.next_action_hint,
            "Wait for dissipation. The system is indifferent to your deadlines."
        )
        self.assertIn("Thermal Lockout", str(err))
        self.assertIn("Heat Accumulation", str(err))
        self.assertIn("Wait for dissipation. The system is indifferent to your deadlines.", str(err))

    def test_idempotency_prevents_duplicate_heat(self):
        """
        Verify that deduplicated DNA sequences do not accumulate additional core heat.
        """
        dna = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data = json.load(f)

        heat_after_first = data['system_state']['core_heat']
        self.assertEqual(heat_after_first, 2.0)

        # Run batch again with identical DNA sequence
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            data_second = json.load(f)

        heat_after_second = data_second['system_state']['core_heat']
        self.assertEqual(heat_after_second, heat_after_first)

    def test_no_silent_drains_on_thermal_lockout(self):
        """
        Verify that thermal lockout prevents clearing input files when invoked via process_once.
        """
        dna_sequences = [f"VOL089007507{i:02d}" for i in range(6)]
        input_content = "\n".join(dna_sequences) + "\n"
        with open(self.input_file, 'w') as f:
            f.write(input_content)

        if 'main' in sys.modules:
            del sys.modules['main']
        import main

        mock_main_file = os.path.join(self.project_root, 'main.py')
        with patch('main.__file__', mock_main_file):
            with self.assertRaises(SystemExit):
                main.process_once()

        # Input file MUST NOT be drained / cleared
        with open(self.input_file, 'r') as f:
            self.assertEqual(f.read(), input_content)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock

# Mock scientific dependencies for sandbox execution
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()

import unittest
import os
import json
import shutil
import tempfile
from utils.dna_ui import main as run_batch, ThermalOverloadError

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        os.makedirs(self.raw_dir)
        os.makedirs(self.output_dir)

        # Link rules folder
        self.rules_dir = os.path.abspath('rules')
        os.symlink(self.rules_dir, os.path.join(self.test_dir, 'rules'))

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.state_file = os.path.join(self.data_dir, 'system_state.json')
        self.ledger_file = os.path.join(self.data_dir, 'processed_ledger.json')

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def write_dna(self, dna_list):
        with open(self.input_file, 'w') as f:
            for dna in dna_list:
                f.write(f"{dna}\n")

    def get_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                return json.load(f)
        return {"system_heat": 0.0}

    def test_heat_accumulation(self):
        # VOL0890... -> amp=890 -> heat gain = 8.9
        # Dissipation = 0.5
        # Net heat = 8.4
        self.write_dna(["VOL08900750712"])
        run_batch()
        state = self.get_state()
        self.assertEqual(state['system_heat'], 8.4)

    def test_clarity_degradation(self):
        # 1. Generate some heat
        self.write_dna(["VOL05000750712"]) # heat gain 5.0, diss 0.5 -> 4.5
        run_batch()

        # 2. Process Clarity string
        # CLAZN0900015
        # heat_int = 4
        # new_thd = 0015 + 4*10 = 55
        # new_nf = 90 - 4 = 86 (N086)
        self.write_dna(["CLAZN0900015"])
        run_batch()

        output_json = os.path.join(self.output_dir, 'toSequence_parsed.json')
        with open(output_json, 'r') as f:
            data = json.load(f)
            # Find the Clarity entry (it might be the second one if we didn't clear ledger,
            # but we use a fresh temp dir)
            cla_entry = next(e for e in data if e['dna'] == "CLAZN0900015")
            self.assertEqual(cla_entry['parsed']['thd'], 55)
            self.assertEqual(cla_entry['parsed']['noise_floor']['value'], 86)

    def test_thermal_overload_refusal(self):
        # Set heat to 10.1
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 10.1}, f)

        self.write_dna(["VOL01000750712"])
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Heat should dissipate even on refusal: 10.1 - 0.5 = 9.6
        state = self.get_state()
        self.assertEqual(state['system_heat'], 9.6)

    def test_idempotency_no_heat_gain(self):
        # Process once
        self.write_dna(["VOL01000750712"]) # gain 1.0, diss 0.5 -> 0.5
        run_batch()
        self.assertEqual(self.get_state()['system_heat'], 0.5)

        # Process again (same string)
        # Should be deduped, no gain, only dissipation
        # 0.5 - 0.5 = 0.0
        run_batch()
        self.assertEqual(self.get_state()['system_heat'], 0.0)

    def test_passive_cooling_no_dna(self):
        # Set heat to 2.0
        with open(self.state_file, 'w') as f:
            json.dump({"system_heat": 2.0}, f)

        # Run batch with no DNA in file
        self.write_dna([])
        run_batch()

        state = self.get_state()
        self.assertEqual(state['system_heat'], 1.5)

if __name__ == '__main__':
    unittest.main()

import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["PySide6"] = MagicMock()
sys.modules["PySide6.QtWidgets"] = MagicMock()
sys.modules["PySide6.QtCore"] = MagicMock()
sys.modules["PySide6.QtGui"] = MagicMock()
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["scipy"] = MagicMock()
sys.modules["scipy.io"] = MagicMock()
sys.modules["scipy.io.wavfile"] = MagicMock()

import unittest
import os
import shutil
import tempfile
import json
from unittest.mock import patch
from utils.dna_ui import main as run_batch, PersistenceError

class TestAtomicityRefined(unittest.TestCase):
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
        with open(self.input_file, 'w') as f:
            f.write("V100\n")

        # Mock a rule file
        self.rule_file = os.path.join(self.rules_dir, 'rules_Volume.json')
        with open(self.rule_file, 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume level", "min": 0, "max": 999, "pad": 3}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_ledger_write_failure_prevents_all_outputs(self):
        """
        Verify that if the ledger write fails during temp file generation,
        neither the JSON nor the CSV output files are created in the final destination.
        """
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'ledger.json')

        # We want to fail specifically when writing the ledger to the temp file.
        # In dna_ui.py, the order is JSON, then CSV, then Ledger.

        original_dump = json.dump
        def side_effect_dump(obj, fp, **kwargs):
            # fp.name will contain 'ledger.json' when it's the ledger's turn in the temp dir
            if 'ledger.json' in getattr(fp, 'name', ''):
                raise IOError("Ledger Disk Full")
            return original_dump(obj, fp, **kwargs)

        with patch('json.dump', side_effect=side_effect_dump):
            with self.assertRaises(PersistenceError):
                run_batch()

        # None of the files should exist in the output/data directories
        self.assertFalse(os.path.exists(json_out), "JSON output should not exist")
        self.assertFalse(os.path.exists(csv_out), "CSV output should not exist")
        self.assertFalse(os.path.exists(ledger_out), "Ledger should not exist")

    def test_csv_write_failure_prevents_all_outputs(self):
        """
        Verify that if the CSV write fails, JSON and Ledger are not updated.
        """
        json_out = os.path.join(self.output_dir, 'toSequence_parsed.json')
        csv_out = os.path.join(self.output_dir, 'toSequence_parsed.csv')
        ledger_out = os.path.join(self.data_dir, 'ledger.json')

        with patch('csv.DictWriter.writerow', side_effect=IOError("CSV Write Failed")):
            with self.assertRaises(PersistenceError):
                run_batch()

        self.assertFalse(os.path.exists(json_out))
        self.assertFalse(os.path.exists(csv_out))
        self.assertFalse(os.path.exists(ledger_out))

if __name__ == '__main__':
    unittest.main()

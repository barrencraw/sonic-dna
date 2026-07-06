import os
import json
import shutil
import unittest
import time
import datetime
from unittest.mock import patch, MagicMock
from utils.dna_ui import main as run_batch, DNAStatus, ThermalOverloadError, save_ledger

class TestFatigue(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join(os.getcwd(), 'test_fatigue_sandbox')
        self.data_dir = os.path.join(self.test_dir, 'data')
        self.raw_dir = os.path.join(self.data_dir, 'raw')
        self.output_dir = os.path.join(self.data_dir, 'output')
        self.rules_dir = os.path.join(self.test_dir, 'rules')

        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rules_dir, exist_ok=True)

        self.input_file = os.path.join(self.raw_dir, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_dir, 'processed_ledger.json')

        # Mock a simple rule
        with open(os.path.join(self.rules_dir, 'rules_Volume.json'), 'w') as f:
            json.dump({
                "variable": "Volume",
                "prefix": "V",
                "subvars": {
                    "level": {"description": "volume", "min": 0, "max": 99, "pad": 2}
                }
            }, f)

        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    @patch('utils.dna_ui.time.time')
    def test_heat_accumulation(self, mock_time):
        mock_time.return_value = 1000.0

        with open(self.input_file, 'w') as f:
            f.write("V10\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 5.0)
        self.assertEqual(state['ledger']['V10']['terminal_outcome'], DNAStatus.SUCCESS.value)

    @patch('utils.dna_ui.time.time')
    def test_heat_dissipation(self, mock_time):
        # 1. Run once to get 5.0 heat
        mock_time.return_value = 1000.0

        # Prepare state manually to avoid datetime.now() mocking issues
        state = {
            "system_heat": 5.0,
            "last_processed_timestamp": datetime.datetime.fromtimestamp(1000.0, datetime.timezone.utc).isoformat(),
            "ledger": {}
        }
        save_ledger(self.ledger_path, state)

        # 2. Advance time by 4 seconds (should dissipate 4 * 0.5 = 2.0 heat)
        mock_time.return_value = 1004.0

        with open(self.input_file, 'w') as f:
            f.write("V20\n")

        # We need to make sure the second run doesn't use a fresh datetime.now()
        # that's far in the future for dissipation math.
        # Wait, the dissipation math uses time.time() for current_time!
        # And last_time is from the ledger.
        # So as long as mock_time is 1004.0 and ledger has 1000.0, dissipation should be 2.0.

        run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        # 5.0 - 2.0 + 5.0 = 8.0
        self.assertAlmostEqual(state['system_heat'], 8.0)

    @patch('utils.dna_ui.time.time')
    def test_thermal_lockout(self, mock_time):
        mock_time.return_value = 1000.0

        # Generate 21 sequences (21 * 5.0 = 105.0)
        # Sequence 21 should trigger lockout (threshold > 100.0)
        # Actually, it checks heat > 100.0 *before* processing.
        # 20 sequences = 100.0 heat. 21st sequence will see 100.0 (not > 100.0)
        # and process, becoming 105.0. 22nd sequence will see 105.0 and trigger lockout.

        sequences = [f"V{i:02d}" for i in range(22)]
        with open(self.input_file, 'w') as f:
            f.write("\n".join(sequences) + "\n")

        with self.assertRaises(ThermalOverloadError):
            run_batch()

        with open(self.ledger_path, 'r') as f:
            state = json.load(f)

        self.assertEqual(state['system_heat'], 105.0)
        # Sequence V21 should be REFUSED
        self.assertEqual(state['ledger']['V21']['terminal_outcome'], DNAStatus.REFUSED.value)
        # Sequence V20 should be SUCCESS
        self.assertEqual(state['ledger']['V20']['terminal_outcome'], DNAStatus.SUCCESS.value)

    @patch('utils.dna_ui.time.time')
    def test_refused_retry(self, mock_time):
        mock_time.return_value = 1000.0

        # Force a lockout state in ledger
        state = {
            "system_heat": 105.0,
            "last_processed_timestamp": datetime.datetime.fromtimestamp(1000.0, datetime.timezone.utc).isoformat(),
            "ledger": {
                "V99": {"terminal_outcome": DNAStatus.REFUSED.value, "timestamp": "..."}
            }
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(state, f)

        # Advance time by 20 seconds (20 * 0.5 = 10.0 dissipation)
        # 105.0 - 10.0 = 95.0 heat. V99 should be allowed.
        mock_time.return_value = 1020.0
        with open(self.input_file, 'w') as f:
            f.write("V99\n")

        run_batch()

        with open(self.ledger_path, 'r') as f:
            new_state = json.load(f)

        self.assertEqual(new_state['ledger']['V99']['terminal_outcome'], DNAStatus.SUCCESS.value)
        # 95.0 + 5.0 = 100.0
        self.assertEqual(new_state['system_heat'], 100.0)

if __name__ == '__main__':
    unittest.main()

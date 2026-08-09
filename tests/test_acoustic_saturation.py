import os
import json
import shutil
import unittest
from unittest.mock import patch
from utils.dna_ui import main as run_batch, AcousticSaturationError

class TestAcousticSaturation(unittest.TestCase):
    def setUp(self):
        # Setup paths
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Backup existing data if any
        self.backup_folder = os.path.join(self.project_root, 'data_backup')
        if os.path.exists(self.data_folder):
            shutil.copytree(self.data_folder, self.backup_folder, dirs_exist_ok=True)

        # Ensure clean state for test
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Initialize empty ledger
        with open(self.ledger_path, 'w') as f:
            json.dump({}, f)

    def tearDown(self):
        # Restore backup
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        if os.path.exists(self.backup_folder):
            shutil.move(self.backup_folder, self.data_folder)

    @patch('time.time')
    def test_volatility_accumulation_normal_and_hf(self, mock_time):
        mock_time.return_value = 1000.0

        # Normal DNA (Volume) and High-Fidelity DNA
        dna_normal = "VOL08900750712"
        dna_hf = "VOL00000000000_HF"

        # 1. Process normal DNA
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertIn('__metadata__', ledger)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 1.0, places=4)

        # 2. Process HF DNA (time hasn't changed, so no decay)
        with open(self.input_file, 'w') as f:
            f.write(dna_hf + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        # 1.0 (previous) + 3.0 (HF) = 4.0
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 4.0, places=4)

    @patch('time.time')
    def test_volatility_decay_over_time(self, mock_time):
        mock_time.return_value = 1000.0
        dna_normal = "VOL08900750712"

        # Process DNA to establish 1.0 volatility at t=1000.0
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 1.0, places=4)

        # Move time forward by 3.0 seconds to t=1003.0
        mock_time.return_value = 1003.0

        # Process another DNA to trigger decay and check volatility
        dna_another = "VOL00000000000"
        with open(self.input_file, 'w') as f:
            f.write(dna_another + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        # Initial: 1.0. 3 seconds elapsed * 0.2 decay/sec = 0.6 decay. Volatility goes down to 0.4.
        # Plus 1.0 for the new normal DNA = 1.4.
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 1.4, places=4)

    @patch('time.time')
    def test_stabilize_control_sequence(self, mock_time):
        mock_time.return_value = 1000.0
        dna_hf = "VOL00000000000_HF"

        # 1. Accumulate volatility using HF (adds 3.0 volatility)
        with open(self.input_file, 'w') as f:
            f.write(dna_hf + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 3.0, places=4)

        # 2. Run STABILIZE
        with open(self.input_file, 'w') as f:
            f.write("STABILIZE\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        # Volatility reduced by 4.0: max(0, 3.0 - 4.0) = 0.0
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 0.0, places=4)
        self.assertIn("STABILIZE", ledger)
        self.assertEqual(ledger["STABILIZE"]["terminal_outcome"], "skipped")

    @patch('time.time')
    def test_lockout_and_no_silent_drains(self, mock_time):
        mock_time.return_value = 1000.0

        # Let's mock system volatility to be exactly 10.0
        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        ledger['__metadata__'] = {
            'system_volatility': 10.0,
            'last_transaction_time': 1000.0
        }
        with open(self.ledger_path, 'w') as f:
            json.dump(ledger, f)

        # Now, try to process a normal DNA sequence. It should trigger lockout and raise AcousticSaturationError.
        dna_normal = "VOL08900750712"
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")

        with self.assertRaises(AcousticSaturationError) as ctx:
            run_batch()

        self.assertIn("Acoustic Saturation Lockout. Volatility threshold exceeded.", str(ctx.exception))
        self.assertIn("Wait for dissipation or run STABILIZE. The system is indifferent to your deadlines.", str(ctx.exception))

        # Check that the STABILIZE sequence is STILL allowed even when locked out
        with open(self.input_file, 'w') as f:
            f.write("STABILIZE\n")
        run_batch() # Should run successfully without raising AcousticSaturationError

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        # Volatility was 10.0. STABILIZE lowers it by 4.0 -> 6.0
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 6.0, places=4)
        self.assertEqual(ledger["STABILIZE"]["terminal_outcome"], "skipped")

    @patch('time.time')
    def test_idempotency_prevents_double_volatility(self, mock_time):
        mock_time.return_value = 1000.0
        dna_normal = "VOL08900750712"

        # 1. Process normal DNA (adds 1.0 volatility)
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 1.0, places=4)

        # 2. Process same DNA again (idempotency key should skip and NOT add volatility)
        with open(self.input_file, 'w') as f:
            f.write(dna_normal + "\n")
        run_batch()

        with open(self.ledger_path, 'r') as f:
            ledger = json.load(f)
        self.assertAlmostEqual(ledger['__metadata__']['system_volatility'], 1.0, places=4)

if __name__ == '__main__':
    unittest.main()

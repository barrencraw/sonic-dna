import os
import json
import shutil
import unittest
import datetime
from unittest.mock import patch

from utils.dna_ui import (
    run_batch,
    load_ledger,
    save_ledger,
    DNAStatus,
    ThermalOverloadError,
    MAX_HEAT,
    HEAT_PER_SEQ,
    COOLING_RATE,
    UI_MESSAGES
)

class MockDatetime:
    timezone = datetime.timezone

    class datetime:
        _now = None

        @classmethod
        def now(cls, tz=None):
            return cls._now

        @classmethod
        def fromisoformat(cls, s):
            return datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))

class TestThermalFatigue(unittest.TestCase):
    def setUp(self):
        self.project_root = os.getcwd()
        self.data_folder = os.path.join(self.project_root, 'data')
        self.raw_folder = os.path.join(self.data_folder, 'raw')
        self.output_folder = os.path.join(self.data_folder, 'output')
        self.input_file = os.path.join(self.raw_folder, 'toSequence.txt')
        self.ledger_path = os.path.join(self.data_folder, 'processed_ledger.json')
        self.json_output = os.path.join(self.output_folder, 'toSequence_parsed.json')

        # Clear existing data
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)
        os.makedirs(self.raw_folder, exist_ok=True)
        os.makedirs(self.output_folder, exist_ok=True)

        # Base time for deterministic datetime checks
        self.base_time = datetime.datetime(2026, 6, 3, 12, 0, 0, tzinfo=datetime.timezone.utc)
        MockDatetime.datetime._now = self.base_time

        # Create a basic rules file for Volume (prefix 'VOL')
        self.rules_folder = os.path.join(self.project_root, 'rules')
        os.makedirs(self.rules_folder, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.data_folder):
            shutil.rmtree(self.data_folder)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_heat_accumulation_per_sequence(self):
        """Verify that processing valid DNA sequences accumulates heat correctly."""
        # 3 valid Volume sequences of length 14
        dna_sequences = ["VOL05000750712", "VOL06000750712", "VOL07000750712"]
        with open(self.input_file, 'w') as f:
            for s in dna_sequences:
                f.write(s + "\n")

        # Initial ledger state
        save_ledger(self.ledger_path, {
            "system_heat": 0.0,
            "last_processed_time": self.base_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        })

        run_batch()

        # Check ledger
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 60.0)
        self.assertEqual(len(ledger["ledger"]), 3)
        for s in dna_sequences:
            self.assertEqual(ledger["ledger"][s]["terminal_outcome"], DNAStatus.SUCCESS)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_dissipation(self):
        """Verify that heat dissipates deterministically based on simulated elapsed time."""
        # Setup ledger with 80.0 heat as of 10 seconds ago
        past_time = self.base_time - datetime.timedelta(seconds=10)
        save_ledger(self.ledger_path, {
            "system_heat": 80.0,
            "last_processed_time": past_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        })

        # Process 1 valid sequence
        dna = "VOL05000750712"
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Heat should dissipate by: 10 seconds * 2.0/s = 20.0
        # 80.0 - 20.0 = 60.0 initial heat on processing start
        # Plus 20.0 heat for processed sequence = 80.0 final heat
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 80.0)

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_thermal_lockout_triggering_and_no_silent_drains(self):
        """Verify that exceeding MAX_HEAT triggers ThermalLockout / ThermalOverloadError and does not clear input."""
        # 6 sequences would require 120.0 heat, exceeding 100.0 limit
        dna_sequences = [
            "VOL01000750712",
            "VOL02000750712",
            "VOL03000750712",
            "VOL04000750712",
            "VOL05000750712",
            "VOL06000750712"
        ]
        with open(self.input_file, 'w') as f:
            for s in dna_sequences:
                f.write(s + "\n")

        save_ledger(self.ledger_path, {
            "system_heat": 0.0,
            "last_processed_time": self.base_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {}
        })

        # Try running batch and expect ThermalOverloadError
        with self.assertRaises(ThermalOverloadError):
            run_batch()

        # Check that the first 5 sequences were processed and committed, and the 6th is NOT
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 100.0)
        self.assertEqual(len(ledger["ledger"]), 5)
        for s in dna_sequences[:5]:
            self.assertEqual(ledger["ledger"][s]["terminal_outcome"], DNAStatus.SUCCESS)
        self.assertNotIn(dna_sequences[5], ledger["ledger"])

        # Validate structured UI keys
        self.assertEqual(UI_MESSAGES["consequence_applied"], "Heat Accumulation")
        self.assertEqual(UI_MESSAGES["refusal_reason"], "Thermal Lockout")
        self.assertEqual(UI_MESSAGES["next_action_hint"], "Wait for dissipation. The system is indifferent to your deadlines.")

    @patch('utils.dna_ui.datetime', MockDatetime)
    def test_idempotency_prevents_heat_accumulation(self):
        """Verify that skipping already processed sequences does not accumulate heat."""
        dna = "VOL05000750712"
        save_ledger(self.ledger_path, {
            "system_heat": 50.0,
            "last_processed_time": self.base_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
            "ledger": {
                dna: {
                    "terminal_outcome": DNAStatus.SUCCESS,
                    "timestamp": self.base_time.strftime('%Y-%m-%dT%H:%M:%SZ')
                }
            }
        })

        # Try to process the same DNA sequence again
        with open(self.input_file, 'w') as f:
            f.write(dna + "\n")

        run_batch()

        # Heat should be unchanged (remains 50.0 as no new processing happened)
        ledger = load_ledger(self.ledger_path)
        self.assertAlmostEqual(ledger["system_heat"], 50.0)

if __name__ == '__main__':
    unittest.main()

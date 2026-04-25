import unittest
import os
import json
import io
from contextlib import redirect_stdout
from dataclasses import is_dataclass
from utils.dna_calculator import ParsedDNA
from utils.dna_ui import Outcome, log_observability

class TestMaintainability(unittest.TestCase):
    def test_parsed_dna_dto(self):
        """Verify ParsedDNA is a dataclass with expected fields."""
        self.assertTrue(is_dataclass(ParsedDNA))
        fields = ParsedDNA.__dataclass_fields__
        self.assertIn('dna', fields)
        self.assertIn('rule', fields)
        self.assertIn('values', fields)

    def test_outcome_enum(self):
        """Verify Outcome enum has all required members."""
        expected_members = {'START', 'END', 'SUCCESS', 'ERROR', 'SKIPPED', 'PROCESSING'}
        actual_members = {m.name for m in Outcome}
        for member in expected_members:
            self.assertIn(member, actual_members)

    def test_log_observability_schema(self):
        """Verify log_observability outputs correctly formatted pipe-delimited JSON."""
        f = io.StringIO()
        with redirect_stdout(f):
            log_observability(
                step="test_step",
                outcome=Outcome.SUCCESS,
                correlation_id="test-uuid",
                extra_field="extra_value"
            )
        output = f.getvalue().strip()

        # Check prefix
        self.assertTrue(output.startswith("| TELEMETRY | "))

        # Check JSON content
        json_str = output.replace("| TELEMETRY | ", "")
        data = json.loads(json_str)

        self.assertEqual(data['step'], "test_step")
        self.assertEqual(data['outcome'], "SUCCESS")
        self.assertEqual(data['correlation_id'], "test-uuid")
        self.assertEqual(data['extra_field'], "extra_value")
        self.assertIn('timestamp', data)
        self.assertEqual(data['chain_name'], "dna_batch_chain")

if __name__ == '__main__':
    unittest.main()

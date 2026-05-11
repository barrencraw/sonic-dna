import unittest
import inspect
from utils.dna_ui import Outcome, ParsedDNA, log_observability

class TestMaintainability(unittest.TestCase):
    def test_outcome_enum_presence(self):
        """Verify Outcome enum has canonical SUCCESS, ERROR, SKIPPED states."""
        self.assertTrue(hasattr(Outcome, 'SUCCESS'))
        self.assertTrue(hasattr(Outcome, 'ERROR'))
        self.assertTrue(hasattr(Outcome, 'SKIPPED'))
        self.assertEqual(Outcome.SUCCESS.value, "success")

    def test_parsed_dna_dto_structure(self):
        """Verify ParsedDNA dataclass has required fields for naming alignment."""
        fields = ParsedDNA.__dataclass_fields__
        self.assertIn('dna', fields)
        self.assertIn('rule', fields)
        self.assertIn('values', fields)
        self.assertIn('error', fields)
        self.assertIn('outcome', fields)

    def test_log_observability_signature(self):
        """Verify log_observability has the required structured fields."""
        sig = inspect.signature(log_observability)
        params = sig.parameters
        required_fields = [
            'correlation_id', 'chain_name', 'step', 'outcome',
            'latency_ms', 'actor_id', 'idempotency_key', 'data'
        ]
        for field in required_fields:
            self.assertIn(field, params, f"Missing required log field: {field}")

if __name__ == '__main__':
    unittest.main()

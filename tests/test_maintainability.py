import unittest
import inspect
from utils.dna_calculator import DNACalculator
from utils.dna_ui import DNAStatus

class TestMaintainability(unittest.TestCase):
    def test_dna_calculator_naming(self):
        """Assert that DNACalculator.parse uses 'dna_sequence' as a parameter name."""
        sig = inspect.signature(DNACalculator.parse)
        self.assertIn('dna_sequence', sig.parameters, "DNACalculator.parse must have a parameter named 'dna_sequence'")

    def test_dna_status_enum(self):
        """Assert that DNAStatus enum exists and has required members."""
        required_members = ['SUCCESS', 'ERROR', 'SKIPPED', 'REFUSED']
        for member in required_members:
            self.assertTrue(hasattr(DNAStatus, member), f"DNAStatus must have member '{member}'")

if __name__ == '__main__':
    unittest.main()

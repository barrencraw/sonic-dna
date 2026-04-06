import unittest
import os
import json
import shutil
import tempfile
from utils.integrity import IntegrityManager

class TestIntegrity(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.state_file = os.path.join(self.test_dir, 'system_integrity.json')
        self.manager = IntegrityManager(state_file=self.state_file)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_default_integrity(self):
        self.assertEqual(self.manager.integrity, 100)

    def test_normal_wear(self):
        parsed_dna = {'rule': 'Volume', 'values': {'amp': 500}}
        change = self.manager.apply_wear(parsed_dna)
        self.assertEqual(change, -2)
        self.assertEqual(self.manager.integrity, 98)

    def test_heavy_load_wear(self):
        # TEX scarcity > 8000
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 9000}}
        change = self.manager.apply_wear(parsed_dna)
        self.assertEqual(change, -5)
        self.assertEqual(self.manager.integrity, 95)

    def test_maintenance_restoration(self):
        self.manager.integrity = 50
        # TEX scarcity < 1000
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        change = self.manager.apply_wear(parsed_dna)
        self.assertEqual(change, 10)
        self.assertEqual(self.manager.integrity, 60)

    def test_integrity_cap(self):
        self.manager.integrity = 95
        parsed_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}
        change = self.manager.apply_wear(parsed_dna)
        self.assertEqual(change, 5) # Capped at 100
        self.assertEqual(self.manager.integrity, 100)

    def test_integrity_floor(self):
        self.manager.integrity = 1
        parsed_dna = {'rule': 'Volume', 'values': {'amp': 500}}
        change = self.manager.apply_wear(parsed_dna)
        self.assertEqual(change, -1) # Floor at 0
        self.assertEqual(self.manager.integrity, 0)

    def test_refusal_at_zero(self):
        self.manager.integrity = 0
        normal_dna = {'rule': 'Volume', 'values': {'amp': 500}}
        maintenance_dna = {'rule': 'Texture Complexity', 'values': {'scarcity': 500}}

        self.assertFalse(self.manager.can_process(normal_dna))
        self.assertTrue(self.manager.can_process(maintenance_dna))

    def test_atomic_save(self):
        self.manager.integrity = 80
        self.manager.save_state()

        # New manager instance should load the saved state
        new_manager = IntegrityManager(state_file=self.state_file)
        self.assertEqual(new_manager.integrity, 80)

if __name__ == '__main__':
    unittest.main()

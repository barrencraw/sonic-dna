#!/usr/bin/env python3
import os
import json

class IntegrityManager:
    def __init__(self, state_file='data/system_integrity.json'):
        self.state_file = state_file
        self.integrity = 100
        self.load()

    def load(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100
        else:
            self.integrity = 100

    def get_integrity(self):
        return self.integrity

    def is_maintenance_dna(self, rule_name, values):
        """
        Maintenance DNA is defined as 'Texture Complexity' (TEX) with scarcity > 8000.
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def calculate_wear(self, outcome, rule_name, values):
        """
        Apply wear or restoration to system integrity based on outcome and rule.
        """
        if self.is_maintenance_dna(rule_name, values):
            # Restoration: +10 (max 100)
            self.integrity = min(100, self.integrity + 10)
            return True # Is maintenance
        else:
            # Non-maintenance wear
            if outcome == 'success':
                self.integrity = max(0, self.integrity - 5)
            elif outcome.startswith('error'):
                self.integrity = max(0, self.integrity - 2)
            return False # Not maintenance

    def get_state(self):
        return {'integrity': self.integrity}

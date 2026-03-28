import os
import json

class IntegrityManager:
    """
    Manages the 'Fatigue' or 'System Integrity' mechanic.
    Integrity is a value from 0 to 100.
    At 0, the system refuses to process non-maintenance DNA.
    """
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

    def is_maintenance_dna(self, rule_name, values):
        """
        Maintenance DNA is defined as a 'Texture Complexity' (TEX) string
        with a scarcity value greater than 8000.
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def calculate_wear(self, rule_name, values):
        """
        Deterministic wear calculation:
        - TEX strings with Scarcity < 2000 drain 5 units.
        - TEX strings with Scarcity > 8000 (Maintenance) restore 10 units (capped at 100).
        - All other processing events result in a standard wear of 2 units.
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity < 2000:
                return -5
            elif scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, wear_amount):
        self.integrity = max(0, min(100, self.integrity + wear_amount))

    def can_process(self, rule_name, values):
        """
        Refusal logic: if integrity is 0, only maintenance DNA is allowed.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

    def to_dict(self):
        return {'integrity': self.integrity}

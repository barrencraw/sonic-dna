import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = 100
        self.load()

    def load(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except (json.JSONDecodeError, IOError):
                self.integrity = 100

    def save_to_dict(self):
        return {'integrity': self.integrity}

    def is_maintenance_dna(self, rule_name, values):
        """
        Maintenance DNA is defined as a 'Texture Complexity' (TEX) string with a scarcity value greater than 8000.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            return scarcity > 8000
        return False

    def calculate_wear(self, rule_name, values):
        """
        Calculates deterministic integrity state transitions:
        - TEX scarcity < 2000: -5 wear.
        - TEX scarcity > 8000 (Maintenance): +10 units (capped at 100).
        - Others: -2 wear.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity < 2000:
                return -5
            elif scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, wear):
        self.integrity = max(0, min(100, self.integrity + wear))
        return self.integrity

    def can_process(self, rule_name, values):
        """
        If integrity hits 0, non-maintenance DNA processing is halted.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

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
            except Exception:
                self.integrity = 100

    def save_to_dict(self):
        return {'integrity': self.integrity}

    def is_maintenance_dna(self, rule_name, values):
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 5000)
            return scarcity < 1000
        return False

    def calculate_wear(self, rule_name, values):
        """
        Returns the integrity change for a successful parse.
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 5000)
            if scarcity < 1000:
                return 10  # Maintenance
            if scarcity > 8000:
                return -5  # Heavy load
        return -2  # Normal wear

    def apply_change(self, delta):
        self.integrity = max(0, min(100, self.integrity + delta))

    def can_process(self, rule_name, values):
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

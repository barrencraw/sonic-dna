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
            except (json.JSONDecodeError, KeyError):
                self.integrity = 100

    def get_state(self):
        return {'integrity': self.integrity}

    def is_maintenance_dna(self, rule_name, values):
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity > 8000:
                return True
        return False

    def calculate_wear(self, rule_name, values):
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity < 2000:
                return -5
            if scarcity > 8000:
                return 10
        return -2

    def apply_wear(self, rule_name, values):
        wear = self.calculate_wear(rule_name, values)
        self.integrity = max(0, min(100, self.integrity + wear))

    def can_process(self, rule_name, values):
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

import json
import os

class IntegrityManager:
    DEFAULT_INTEGRITY = 100
    MAX_INTEGRITY = 100
    MIN_INTEGRITY = 0

    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return max(self.MIN_INTEGRITY, min(self.MAX_INTEGRITY, data.get('integrity', self.DEFAULT_INTEGRITY)))
            except (json.JSONDecodeError, KeyError, Exception):
                return self.DEFAULT_INTEGRITY
        return self.DEFAULT_INTEGRITY

    def save_state(self, target_path=None):
        path = target_path or self.state_path
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)

    def calculate_wear(self, rule_name, values):
        """
        Calculates wear/restoration impact based on scarcity.
        Returns: integer (negative for wear, positive for restoration).
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 1000:
                return 10  # Maintenance
            elif scarcity > 8000:
                return -5  # Heavy Load
            else:
                return -2  # Normal Load
        return -2 # Default for other rules

    def is_maintenance_dna(self, rule_name, values):
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            return scarcity < 1000
        return False

    def apply_impact(self, impact):
        self.integrity = max(self.MIN_INTEGRITY, min(self.MAX_INTEGRITY, self.integrity + impact))

    def is_refusing(self):
        return self.integrity <= self.MIN_INTEGRITY

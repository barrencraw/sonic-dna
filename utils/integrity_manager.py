import os
import json

class IntegrityManager:
    def __init__(self, integrity_path, initial_integrity=100):
        self.integrity_path = integrity_path
        self.integrity = self._load_integrity(initial_integrity)

    def _load_integrity(self, default_value):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', default_value)
            except (json.JSONDecodeError, KeyError, OSError):
                return default_value
        return default_value

    def calculate_wear(self, rule_name, values):
        """
        Determines the integrity change based on DNA parsing results.
        Returns the integer amount of wear (negative for restoration).
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 2000:
                return 5  # High complexity wear
            elif scarcity > 8000:
                return -10  # Maintenance restore
        return 2  # Standard wear

    def apply_wear(self, amount):
        """
        Updates the internal integrity state based on wear amount.
        """
        self.integrity = max(0, min(100, self.integrity - amount))

    def is_refused(self, rule_name, values):
        """
        Returns True if the system is at 0 integrity and the DNA is not a maintenance task.
        """
        if self.integrity > 0:
            return False

        # Maintenance bypasses refusal
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity > 8000:
                return False

        return True

    def get_state(self):
        return {'integrity': self.integrity}

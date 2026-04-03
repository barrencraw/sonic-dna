import os
import json

class IntegrityManager:
    def __init__(self, state_file='data/system_integrity.json'):
        self.state_file = state_file
        self.integrity = self._load_integrity()

    def _load_integrity(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, KeyError):
                return 100
        return 100

    def save_integrity(self, tmp_dir=None):
        data = {'integrity': self.integrity}
        if tmp_dir:
            tmp_path = os.path.join(tmp_dir, os.path.basename(self.state_file))
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return tmp_path
        else:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def apply_wear(self, rule_name, values):
        """
        Calculate and apply wear based on the rule and parsed values.
        Returns the amount of wear/restoration applied.
        """
        if self.is_maintenance_dna(rule_name, values):
            change = 10
        elif rule_name == "Texture Complexity" and values.get('scarcity', 5000) < 2000:
            change = -5
        else:
            change = -2

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        return self.integrity - old_integrity

    def is_maintenance_dna(self, rule_name, values):
        """
        A TEX string with scarcity > 9000 is maintenance.
        """
        if rule_name == "Texture Complexity" and values.get('scarcity', 0) > 9000:
            return True
        return False

    def can_process(self, rule_name, values):
        """
        Can process if integrity > 0 OR if it's a maintenance DNA.
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

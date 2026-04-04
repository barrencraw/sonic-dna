import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = self._load_integrity()

    def _load_integrity(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, KeyError, IOError):
                return 100
        return 100

    def save_integrity(self, integrity, tmp_dir=None):
        self.integrity = max(0, min(100, integrity))
        data = {'integrity': self.integrity}

        if tmp_dir:
            tmp_path = os.path.join(tmp_dir, os.path.basename(self.state_path))
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return tmp_path
        else:
            with open(self.state_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return self.state_path

    def get_integrity_change(self, rule_name, values):
        """
        Calculates the change in integrity for a given DNA string.
        - Maintenance: +10 if TEX scarcity < 1000.
        - Heavy Load: -5 if TEX scarcity > 8000.
        - Normal Wear: -2 otherwise.
        """
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 1000:
                return 10
            elif scarcity > 8000:
                return -5

        return -2

    def is_maintenance_dna(self, rule_name, values):
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 5000)
            if scarcity < 1000:
                return True
        return False

    def can_process(self, rule_name, values):
        """
        Returns True if the DNA can be processed given current integrity.
        Maintenance DNA can always be processed (to allow restoration).
        """
        if self.integrity > 0:
            return True
        return self.is_maintenance_dna(rule_name, values)

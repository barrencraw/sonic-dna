import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, integrity_path):
        self.integrity_path = integrity_path
        self.integrity = 100
        self.load()

    def load(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100
        else:
            self.integrity = 100

    def save(self):
        directory = os.path.dirname(self.integrity_path)
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=directory) as tmp_dir:
            tmp_path = os.path.join(tmp_dir, 'integrity.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'integrity': self.integrity}, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.integrity_path)

    def calculate_wear(self, rule_name, values):
        """
        Calculates integrity change.
        Standard: -1
        High Complexity (TEX, scarcity > 5000): -5
        Maintenance (TEX, scarcity < 1000): +20
        """
        if rule_name == 'Texture Complexity':
            scarcity = values.get('scarcity', 0)
            if scarcity < 1000:
                return 20
            if scarcity > 5000:
                return -5
        return -1

    def can_process(self, rule_name, values):
        """
        Maintenance is always allowed.
        High Complexity requires integrity >= 10.
        Standard requires integrity >= 1.
        """
        if rule_name == 'Texture Complexity' and values.get('scarcity', 0) < 1000:
            return True

        if rule_name == 'Texture Complexity' and values.get('scarcity', 0) > 5000:
            return self.integrity >= 10

        return self.integrity >= 1

    def apply_change(self, change):
        self.integrity = max(0, min(100, self.integrity + change))

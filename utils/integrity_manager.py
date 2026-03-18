import os
import json

class IntegrityManager:
    def __init__(self, state_path):
        self.state_path = state_path
        self.integrity = self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except (json.JSONDecodeError, KeyError):
                return 100
        return 100

    def apply_wear(self, rule_name, scarcity=None):
        if rule_name == 'Texture Complexity':
            if scarcity is not None:
                if scarcity < 2000:
                    self.integrity = max(0, self.integrity - 5)
                elif scarcity > 8000:
                    self.integrity = min(100, self.integrity + 10)
                else:
                    self.integrity = max(0, self.integrity - 2)
            else:
                self.integrity = max(0, self.integrity - 2)
        else:
            self.integrity = max(0, self.integrity - 2)

    def is_operational(self, rule_name, scarcity=None):
        # Maintenance DNA (TEX scarcity > 8000) is always allowed.
        if rule_name == 'Texture Complexity' and scarcity is not None and scarcity > 8000:
            return True
        return self.integrity > 0

    def save_state(self, target_path=None):
        path = target_path or self.state_path
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())

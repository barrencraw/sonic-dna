import os
import json
import tempfile

class IntegrityManager:
    def __init__(self, integrity_path, messages_path):
        self.integrity_path = integrity_path
        self.messages_path = messages_path
        self.integrity = self._load_integrity()
        self.messages = self._load_messages()

    def _load_integrity(self):
        if os.path.exists(self.integrity_path):
            try:
                with open(self.integrity_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', 100)
            except Exception:
                return 100
        return 100

    def _load_messages(self):
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_integrity(self, tmp_dir=None):
        data = {'integrity': self.integrity}

        if tmp_dir:
            tmp_file = os.path.join(tmp_dir, 'system_integrity.json')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, self.integrity_path)
        else:
            # Fallback if no tmp_dir provided (not recommended for production but good for tests)
            with open(self.integrity_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

    def is_maintenance(self, result):
        """
        Check if the DNA result (from DNACalculator.parse) is maintenance.
        Maintenance = Texture Complexity (TEX) with scarcity < 1000.
        """
        if result['rule'] == 'Texture Complexity':
            scarcity = result['values'].get('scarcity', 10000)
            return scarcity < 1000
        return False

    def is_heavy_load(self, result):
        """
        Check if the DNA result is heavy load.
        Heavy Load = Texture Complexity (TEX) with scarcity > 8000.
        """
        if result['rule'] == 'Texture Complexity':
            scarcity = result['values'].get('scarcity', 0)
            return scarcity > 8000
        return False

    def can_process(self, result):
        """
        At 0 integrity, only maintenance DNA is allowed.
        """
        if self.integrity <= 0:
            return self.is_maintenance(result)
        return True

    def apply_wear(self, result):
        """
        Apply wear or maintenance restoration based on the DNA parse result.
        Returns the change value.
        """
        if self.is_maintenance(result):
            change = 10
        elif self.is_heavy_load(result):
            change = -5
        else:
            change = -2

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        actual_change = self.integrity - old_integrity

        return actual_change

    def get_message(self, key, **kwargs):
        msg = self.messages.get(key, "")
        return msg.format(**kwargs)

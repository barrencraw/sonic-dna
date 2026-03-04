import os
import json

DEFAULT_INTEGRITY = 100
MAX_INTEGRITY = 100
MIN_INTEGRITY = 0

class IntegrityManager:
    def __init__(self, filepath='data/system_integrity.json'):
        self.filepath = filepath
        self.integrity = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('integrity', DEFAULT_INTEGRITY)
            except (json.JSONDecodeError, OSError):
                return DEFAULT_INTEGRITY
        return DEFAULT_INTEGRITY

    def save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f, indent=2)

    def adjust(self, amount):
        old_integrity = self.integrity
        self.integrity = max(MIN_INTEGRITY, min(MAX_INTEGRITY, self.integrity + amount))
        self.save()
        return self.integrity - old_integrity

    def get_status(self):
        return self.integrity

    def can_process(self, drain_amount=0):
        # Even if it drains, we might allow it if current is > 0
        # But if drain is required and we are at 0, refuse.
        if drain_amount > 0 and self.integrity <= 0:
            return False
        return True

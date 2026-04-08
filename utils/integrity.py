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

    def save(self):
        dir_name = os.path.dirname(self.integrity_path) or '.'
        with tempfile.TemporaryDirectory(dir=dir_name) as tmp_dir:
            tmp_path = os.path.join(tmp_dir, 'integrity.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'integrity': self.integrity}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.integrity_path)

    def is_maintenance(self, dna_str):
        if dna_str.startswith("TEX"):
            try:
                # TEX is prefix (3 chars), scarcity is 5 chars
                scarcity = int(dna_str[3:8])
                return scarcity < 1000
            except (ValueError, IndexError):
                return False
        return False

    def is_heavy_load(self, dna_str):
        if dna_str.startswith("TEX"):
            try:
                scarcity = int(dna_str[3:8])
                return scarcity > 8000
            except (ValueError, IndexError):
                return False
        return False

    def can_process(self, dna_str):
        if self.integrity > 0:
            return True
        return self.is_maintenance(dna_str)

    def apply_wear(self, dna_str):
        if self.is_maintenance(dna_str):
            change = 10
        elif self.is_heavy_load(dna_str):
            change = -5
        else:
            change = -2

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + change))
        actual_change = self.integrity - old_integrity

        msg_template = self.messages.get('integrity', {}).get('consequence_applied', 'Integrity changed by {change}. Value: {integrity}.')
        return msg_template.format(change=actual_change, integrity=self.integrity)

    def get_refusal_message(self):
        m = self.messages.get('integrity', {})
        reason = m.get('refusal_reason', 'System integrity is 0.')
        hint = m.get('next_action_hint', 'Maintenance required.')
        return f"{reason} {hint}"

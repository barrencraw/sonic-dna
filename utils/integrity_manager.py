import os
import json

class IntegrityManager:
    def __init__(self, state_path='data/system_integrity.json', messages_path='data/system_messages.json'):
        self.state_path = state_path
        self.messages_path = messages_path
        self.integrity = 100
        self.messages = {}
        self.load()

    def load(self):
        # Load integrity state
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.integrity = data.get('integrity', 100)
            except Exception:
                self.integrity = 100
        else:
            self.integrity = 100

        # Load system messages
        if os.path.exists(self.messages_path):
            try:
                with open(self.messages_path, 'r', encoding='utf-8') as f:
                    self.messages = json.load(f)
            except Exception:
                self.messages = {}

    def save(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(self.state_path, 'w', encoding='utf-8') as f:
            json.dump({'integrity': self.integrity}, f)

    def apply_dna_impact(self, rule_name, values):
        """
        TEX DNA with layering > 500 or variation > 7000 drains 10 integrity.
        TEX DNA with scarcity > 9000 restores 5 integrity.
        """
        if rule_name != "Texture Complexity":
            return 0

        drain = 0
        restore = 0

        layering = values.get('layering', 0)
        variation = values.get('variation', 0)
        scarcity = values.get('scarcity', 0)

        if layering > 500 or variation > 7000:
            drain = 10

        if scarcity > 9000:
            restore = 5

        impact = restore - drain
        if impact == 0:
            return 0

        old_integrity = self.integrity
        self.integrity = max(0, min(100, self.integrity + impact))
        actual_impact = self.integrity - old_integrity

        if actual_impact != 0:
            msg_tmpl = self.messages.get('consequence_applied', "System integrity shifted by {impact}%. Current: {current}%")
            print(f"[OBSERVABILITY] {msg_tmpl.format(impact=actual_impact, current=self.integrity)}")

        return actual_impact

    def can_process(self, rule_name, values):
        """
        Processing refused if integrity is 0, unless it's a maintenance string (scarcity > 9000).
        """
        if self.integrity > 0:
            return True

        is_maintenance = False
        if rule_name == "Texture Complexity":
            scarcity = values.get('scarcity', 0)
            if scarcity > 9000:
                is_maintenance = True

        if is_maintenance:
            return True

        msg_tmpl = self.messages.get('refusal_reason', "Insufficient system integrity ({current}%).")
        hint = self.messages.get('next_action_hint', "")
        print(f"[OBSERVABILITY] {msg_tmpl.format(current=self.integrity)}")
        if hint:
            print(f"[OBSERVABILITY] {hint}")

        return False

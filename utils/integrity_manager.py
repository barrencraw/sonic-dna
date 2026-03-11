import json

class IntegrityManager:
    def __init__(self, integrity_state):
        """
        integrity_state: dict like {"integrity": 100}
        """
        self.state = integrity_state
        self.max_integrity = 100
        self.min_integrity = 0
        self.drain_amount = 10
        self.restore_amount = 5

    def get_integrity(self):
        return self.state.get("integrity", self.max_integrity)

    def is_refusal_state(self):
        return self.get_integrity() <= self.min_integrity

    def is_maintenance_string(self, rule_name, parsed_values):
        """
        Determines if a DNA string is a maintenance string (restores integrity).
        Rule: TEX DNA with scarcity > 9000.
        """
        if rule_name == "Texture Complexity":
            scarcity = parsed_values.get("scarcity", 0)
            if scarcity > 9000:
                return True
        return False

    def apply_consequences(self, rule_name, parsed_values):
        """
        Applies integrity drain or restore based on the DNA.
        Returns (change_applied: bool, message_key: str or None)
        """
        initial_integrity = self.get_integrity()

        # Restore logic
        if self.is_maintenance_string(rule_name, parsed_values):
            new_integrity = min(self.max_integrity, initial_integrity + self.restore_amount)
            self.state["integrity"] = new_integrity
            return (new_integrity != initial_integrity), "integrity_restored"

        # Drain logic
        if rule_name == "Texture Complexity":
            layering = parsed_values.get("layering", 0)
            variation = parsed_values.get("variation", 0)

            if layering > 500 or variation > 7000:
                new_integrity = max(self.min_integrity, initial_integrity - self.drain_amount)
                self.state["integrity"] = new_integrity
                return (new_integrity != initial_integrity), "consequence_applied"

        return False, None

import os
import ast
import unittest
import utils.dna_ui as dna_ui
import utils.dna_calculator as dna_calculator

class TestMaintainability(unittest.TestCase):
    def test_canonical_naming_in_dna_calculator(self):
        """Ensure dna_calculator uses 'dna_sequence' in its parse methods."""
        filepath = os.path.join('utils', 'dna_calculator.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())

        found_parse = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'parse':
                found_parse = True
                arg_names = [arg.arg for arg in node.args.args]
                self.assertIn('dna_sequence', arg_names, f"Function 'parse' in {filepath} missing 'dna_sequence' argument")
                self.assertNotIn('dna_string', arg_names, f"Function 'parse' in {filepath} should not use 'dna_string'")

        self.assertTrue(found_parse, "Could not find any 'parse' function in dna_calculator.py")

    def test_canonical_naming_in_dna_ui(self):
        """Ensure dna_ui uses 'dna_sequences' in its main processing logic."""
        filepath = os.path.join('utils', 'dna_ui.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # Check for 'dna_sequences' and absence of 'dna_list'
        self.assertIn('dna_sequences', content)
        self.assertNotIn('dna_list', content)
        self.assertNotIn('dna_str', content)

    def test_explicit_terminal_states(self):
        """Ensure TerminalOutcome enum is defined and used."""
        self.assertTrue(hasattr(dna_ui, 'TerminalOutcome'), "TerminalOutcome Enum missing from dna_ui")
        expected_members = {'SUCCESS', 'PARSE_ERROR', 'SKIPPED'}
        actual_members = {m.name for m in dna_ui.TerminalOutcome}
        for member in expected_members:
            self.assertIn(member, actual_members)

    def test_structured_logging_keys(self):
        """Ensure log_structured exists and has standard keys."""
        self.assertTrue(hasattr(dna_ui, 'log_structured'), "log_structured function missing from dna_ui")

        # We can also check the implementation via AST if we want to be very strict
        filepath = os.path.join('utils', 'dna_ui.py')
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'log_structured':
                # Check for standard keys in the dictionary construction
                found_keys = set()
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Dict):
                        for key in subnode.keys:
                            if isinstance(key, ast.Constant):
                                found_keys.add(key.value)

                required_keys = {'timestamp', 'correlation_id', 'chain_name', 'step', 'outcome'}
                for rkey in required_keys:
                    self.assertIn(rkey, found_keys, f"log_structured missing required log key: {rkey}")

if __name__ == '__main__':
    unittest.main()

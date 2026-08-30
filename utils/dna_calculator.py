#!/usr/bin/env python3
import os
import json
import re

class RuleParseError(Exception):
    pass

class Rule:
    def __init__(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            self.raw = json.load(f)
        # Required keys
        self.variable = self.raw.get('variable')
        self.prefix = self.raw.get('prefix')
        self.subvars = self.raw.get('subvars', {})
        if not self.variable or not self.prefix or not self.subvars:
            raise RuleParseError(f"Invalid rule file: {filepath}")
        # Precompute a parsing plan (list of (name, schema)) in insertion order
        self.plan = []
        for subvar_name, subvar_schema in self.subvars.items():
            self.plan.append((subvar_name, subvar_schema))

    def parse(self, dna_sequence):
        """
        Given a DNA sequence (complete, including prefix), return a nested dict:
        { subvar_name: value or {child: ...}, ... }.
        """
        if not dna_sequence.startswith(self.prefix):
            raise RuleParseError(f"DNA sequence '{dna_sequence}' does not start with prefix '{self.prefix}'")
        idx = len(self.prefix)
        values = {}
        for subvar_name, subvar_schema in self.plan:
            val, idx = self._parse_subvar(subvar_schema, dna_sequence, idx)
            values[subvar_name] = val
        # If idx != len(dna_sequence), leftover characters
        if idx != len(dna_sequence):
            raise RuleParseError(
                f"Extra characters after parsing rule '{self.variable}': "
                f"parsed up to index {idx}, string length {len(dna_sequence)}"
            )
        return values

    def serialize(self, values_dict):
        """
        Given a nested dict of values matching this rule’s subvars, rebuild the DNA string.
        """
        dna = [self.prefix]
        for subvar_name, subvar_schema in self.plan:
            if subvar_name not in values_dict:
                raise RuleParseError(f"Missing subvar '{subvar_name}' for rule '{self.variable}'")
            dna_part = self._serialize_subvar(subvar_schema, values_dict[subvar_name])
            dna.append(dna_part)
        return ''.join(dna)

    def _parse_subvar(self, schema, dna, idx):
        """
        Recursively parse one subvar. Returns (parsed_value, new_idx).
        parsed_value is either a leaf (int, str, or dict for composite) or nested dict.
        """
        # If 'description' in schema, it’s a leaf schema. Otherwise, it's a group of children.
        if 'description' in schema and (
            'min' in schema or 'class' in schema or 'class_order' in schema
            or 'band_class' in schema or 'index_min' in schema
        ):
            # Leaf case
            return self._parse_leaf(schema, dna, idx)
        else:
            # Group (nested subfields)
            result = {}
            for child_name, child_schema in schema.items():
                # Each child is itself a schema (leaf or group)
                val, idx = self._parse_subvar(child_schema, dna, idx)
                result[child_name] = val
            return result, idx

    def _parse_leaf(self, schema, dna, idx):
        """
        Figure out which pattern this leaf uses and parse accordingly.
        Returns (value, new_idx).
        - Numeric-only (min, max, pad)
        - Numeric+sign  (min, max, pad, sign)
        - Class-only (class or class_order)
        - Composite (e.g. band_class + hz_pad; index_pad + rate_class + links_pad)
        """
        # 1) Composite: root of Frequency: band_class + hz_pad
        if 'band_class' in schema and 'hz_pad' in schema:
            # First char = class letter; next hz_pad digits = integer
            length = 1 + schema['hz_pad']
            fragment = dna[idx:idx+length]
            if len(fragment) < length:
                raise RuleParseError(f"Unexpected end of string parsing composite at idx {idx}")
            cls = fragment[0]
            num_str = fragment[1:]
            if not num_str.isdigit():
                raise RuleParseError(f"Expected {schema['hz_pad']} digits for hz, got '{num_str}'")
            return {'band': cls, 'hz': int(num_str)}, idx + length

        # 2) Composite FM: index_pad digits + rate_class letter + links_pad digits
        if 'index_pad' in schema and 'rate_class' in schema and 'links_pad' in schema:
            ip = schema['index_pad']
            lp = schema['links_pad']
            total_len = ip + 1 + lp
            fragment = dna[idx:idx+total_len]
            if len(fragment) < total_len:
                raise RuleParseError(f"Unexpected end parsing FM composite at idx {idx}")
            num_index = fragment[0:ip]
            rate_letter = fragment[ip]
            num_links = fragment[ip+1: ip+1+lp]
            if not (num_index.isdigit() and num_links.isdigit()):
                raise RuleParseError(f"FM composite numeric parse error at idx {idx}")
            return {
                'index': int(num_index),
                'rate': rate_letter,
                'links': int(num_links)
            }, idx + total_len

        # 3) Sign + numeric (micro-tuning, noise_floor, spectral_tilt, etc.)
        if 'min' in schema and 'max' in schema and 'pad' in schema and 'sign' in schema:
            # Sign = 1 character, numeric = pad digits
            pad = schema['pad']
            length = 1 + pad
            fragment = dna[idx:idx+length]
            if len(fragment) < length:
                raise RuleParseError(f"Unexpected end parsing signed numeric at idx {idx}")
            sign_char = fragment[0]
            num_str = fragment[1:]
            if not num_str.isdigit():
                raise RuleParseError(f"Expected {pad} digits, got '{num_str}'")
            val = int(num_str)
            return {'sign': sign_char, 'value': val}, idx + length

        # 4) Hz composites inside Perceived Pitch: fundamental/harmonic_centroid each min,max,pad
        if 'min' in schema and 'max' in schema and 'pad' in schema and 'description' in schema and 'hz_' not in schema:
            # If a leaf with numeric-only (no sign, no class): pad digits
            pad = schema['pad']
            fragment = dna[idx:idx+pad]
            if len(fragment) < pad or not fragment.isdigit():
                raise RuleParseError(f"Unexpected numeric parse at idx {idx}: got '{fragment}'")
            return int(fragment), idx + pad

        # 5) Pure class(es): single-letter or multi-letter (class or class_order)
        if ('class' in schema or 'class_order' in schema) and 'min' not in schema and 'band_class' not in schema and 'index_min' not in schema:
            class_order = schema.get('class') or schema.get('class_order')
            # Determine delimiter – could be '-' or '–'
            if '–' in class_order:
                codes = class_order.split('–')
            else:
                codes = class_order.split('-')
            first_code = codes[0]
            length = len(first_code)
            fragment = dna[idx:idx+length]
            if len(fragment) < length:
                raise RuleParseError(f"Unexpected end parsing class at idx {idx}")
            return fragment, idx + length

        # Catch-all: numeric-only with min,max,pad
        if 'min' in schema and 'max' in schema and 'pad' in schema:
            pad = schema['pad']
            fragment = dna[idx:idx+pad]
            if len(fragment) < pad or not fragment.isdigit():
                raise RuleParseError(f"Numeric field parse error at idx {idx}: got '{fragment}'")
            return int(fragment), idx + pad

        # Should not get here
        raise RuleParseError(f"Unrecognized leaf schema at idx {idx}: {schema}")

    def _serialize_subvar(self, schema, value):
        """
        Serialize a single subvar (leaf or group) given the value(s).
        """
        # Leaf: has 'description' and one of the identifying keys
        if 'description' in schema and (
            'min' in schema or 'class' in schema or 'band_class' in schema
            or 'index_min' in schema
        ):
            return self._serialize_leaf(schema, value)
        # Group: iterate child schemas
        parts = []
        for child_name, child_schema in schema.items():
            if child_name not in value:
                raise RuleParseError(f"Missing nested '{child_name}' in value {value}")
            parts.append(self._serialize_subvar(child_schema, value[child_name]))
        return ''.join(parts)

    def _serialize_leaf(self, schema, value):
        """
        Build the exact substring corresponding to this leaf schema.
        """
        # 1) Composite: band_class + hz_pad
        if 'band_class' in schema and 'hz_pad' in schema:
            cls = value.get('band')
            hz = value.get('hz')
            if cls is None or hz is None:
                raise RuleParseError(f"Expected 'band' and 'hz' in {value}")
            hz_pad = schema['hz_pad']
            return f"{cls}{str(hz).zfill(hz_pad)}"

        # 2) Composite FM: index_pad + rate_class + links_pad
        if 'index_pad' in schema and 'rate_class' in schema and 'links_pad' in schema:
            ip = schema['index_pad']
            lp = schema['links_pad']
            idx_num = value.get('index')
            rate = value.get('rate')
            links = value.get('links')
            if idx_num is None or rate is None or links is None:
                raise RuleParseError(f"Expected 'index', 'rate', 'links' in {value}")
            return f"{str(idx_num).zfill(ip)}{rate}{str(links).zfill(lp)}"

        # 3) Sign + numeric
        if 'sign' in schema and 'pad' in schema and 'min' in schema:
            sign_char = value.get('sign')
            num = value.get('value')
            if sign_char is None or num is None:
                raise RuleParseError(f"Expected dict with 'sign' and 'value' for {schema}")
            pad = schema['pad']
            return f"{sign_char}{str(num).zfill(pad)}"

        # 4) Pure numeric (min,max,pad)
        if 'min' in schema and 'max' in schema and 'pad' in schema and 'band_class' not in schema and 'index_min' not in schema:
            pad = schema['pad']
            if not isinstance(value, int):
                raise RuleParseError(f"Expected int for numeric field, got {value}")
            return str(value).zfill(pad)

        # 5) Pure class (class or class_order)
        if ('class' in schema or 'class_order' in schema) and 'min' not in schema and 'band_class' not in schema:
            # Value should be a string of correct length
            class_order = schema.get('class') or schema.get('class_order')
            if not isinstance(value, str):
                raise RuleParseError(f"Expected str for class field, got {value}")
            # Check length matches first code length
            if '–' in class_order:
                codes = class_order.split('–')
            else:
                codes = class_order.split('-')
            first_code = codes[0]
            needed = len(first_code)
            if len(value) != needed:
                raise RuleParseError(f"Expected class of length {needed}, got '{value}'")
            return value

        # Should not get here
        raise RuleParseError(f"Cannot serialize leaf schema: {schema}")


class DNACalculator:
    def __init__(self, rules_folder='rules'):
        """
        Loads all .json rule files from `rules_folder`.
        """
        self.rules = {}  # prefix -> Rule instance
        self._load_rules(rules_folder)

    def _load_rules(self, folder):
        if not os.path.isdir(folder):
            raise FileNotFoundError(f"Rules folder not found: '{folder}'")
        for fname in os.listdir(folder):
            if fname.lower().endswith('.json'):
                path = os.path.join(folder, fname)
                rule = Rule(path)
                if rule.prefix in self.rules:
                    raise RuleParseError(f"Duplicate prefix '{rule.prefix}' in {fname}")
                self.rules[rule.prefix] = rule

    def parse(self, dna_sequence):
        """
        Identify which rule applies (by prefix), then parse.
        Returns { 'rule': variable_name, 'values': nested_dict }.
        """
        # Try to match any known prefix
        for prefix, rule in self.rules.items():
            if dna_sequence.startswith(prefix):
                parsed = rule.parse(dna_sequence)
                return {'rule': rule.variable, 'values': parsed}
        raise RuleParseError(f"No matching rule for DNA sequence '{dna_sequence}'")

    def serialize(self, variable_name, values_dict):
        """
        Given a variable name (the human-readable name, e.g. "Volume"),
        find the rule and serialize values to DNA string.
        """
        for rule in self.rules.values():
            if rule.variable == variable_name:
                return rule.serialize(values_dict)
        raise RuleParseError(f"No rule found for variable '{variable_name}'")

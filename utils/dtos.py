from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

class ProcessingOutcome(Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    DEDUPE = "DEDUPE"

@dataclass
class DNAResult:
    dna_string: str
    rule_name: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    outcome: ProcessingOutcome = ProcessingOutcome.SUCCESS
    error_message: Optional[str] = None

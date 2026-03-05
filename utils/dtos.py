from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Dict

class ProcessingOutcome(Enum):
    SUCCESS = "success"
    ERROR = "error"
    DEDUPE = "dedupe"

@dataclass
class DNAResult:
    dna: str
    rule: Optional[str] = None
    values: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    outcome: Optional[ProcessingOutcome] = None

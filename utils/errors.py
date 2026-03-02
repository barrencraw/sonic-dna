"""
utils/errors.py

A precise error model for SonicDNA, enforcing classification and retryability.
"""

class SonicDNAError(Exception):
    """Base class for all SonicDNA exceptions."""
    def __init__(self, message, error_class, retryable, cause_type=None):
        super().__init__(message)
        self.error_class = error_class
        self.retryable = retryable
        self.cause_type = cause_type or self.__class__.__name__

class DomainInvariantError(SonicDNAError):
    """Domain logic violated; non-retryable."""
    def __init__(self, message, cause_type=None):
        super().__init__(message, "Domain Invariant", False, cause_type)

class BoundaryValidationError(SonicDNAError):
    """Input validation failed at boundary; non-retryable."""
    def __init__(self, message, cause_type=None):
        super().__init__(message, "Boundary Validation", False, cause_type)

class InfraTransientError(SonicDNAError):
    """Temporary infrastructure failure; retryable."""
    def __init__(self, message, cause_type=None):
        super().__init__(message, "Infra Transient", True, cause_type)

class InfraPermanentError(SonicDNAError):
    """Permanent infrastructure failure; non-retryable."""
    def __init__(self, message, cause_type=None):
        super().__init__(message, "Infra Permanent", False, cause_type)

# Specific exceptions for the DNA Batch Parsing chain

class DNAFormatError(BoundaryValidationError):
    """Raised when DNA string does not match the expected format or prefix."""
    pass

class RuleDefinitionError(DomainInvariantError):
    """Raised when a rule file is malformed or missing required keys."""
    pass

class InputReadError(InfraPermanentError):
    """Raised when the input DNA file cannot be read."""
    pass

class PersistenceError(InfraPermanentError):
    """Raised when writing or moving output files fails."""
    pass

class LedgerError(InfraPermanentError):
    """Raised when the idempotency ledger cannot be loaded or saved."""
    pass

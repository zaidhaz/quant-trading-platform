class DomainError(Exception):
    """Base class for all domain exceptions."""


class ValidationError(DomainError):
    """Input failed validation."""


class InsufficientDataError(DomainError):
    """Not enough historical data to compute a requested value (e.g. indicator warmup)."""


class InvalidBacktestConfigError(DomainError):
    """A backtest was configured inconsistently (bad date range, unknown strategy, etc.)."""


class RiskRejectedError(DomainError):
    """A signal was rejected by the risk engine before becoming an order."""


class DataGapError(DomainError):
    """The historical data store has a gap in the requested range."""

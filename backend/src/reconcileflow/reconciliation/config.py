"""Configuration for deterministic reconciliation rules."""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    amount_tolerance: Decimal = Decimal("1.00")
    date_tolerance_days: int = 14
    maximum_group_size: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.amount_tolerance, Decimal):
            raise TypeError("amount_tolerance must be Decimal")
        if self.amount_tolerance < 0:
            raise ValueError("amount_tolerance cannot be negative")
        if isinstance(self.date_tolerance_days, bool) or self.date_tolerance_days < 0:
            raise ValueError("date_tolerance_days must be a non-negative integer")
        if isinstance(self.maximum_group_size, bool) or not 2 <= self.maximum_group_size <= 10:
            raise ValueError("maximum_group_size must be between 2 and 10")

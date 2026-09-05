"""Explainable output produced by the reconciliation engine."""

from dataclasses import dataclass
from decimal import Decimal

from reconcileflow.models import ReconciliationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationResult:
    result_id: str
    status: ReconciliationStatus
    rule: str
    bank_source_record_ids: tuple[str, ...] = ()
    erp_invoice_ids: tuple[str, ...] = ()
    gateway_source_record_ids: tuple[str, ...] = ()
    expected_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    amount_difference: Decimal | None = None
    currency: str | None = None
    explanation: str
    requires_review: bool = False

    def __post_init__(self) -> None:
        if not self.result_id.strip() or not self.rule.strip() or not self.explanation.strip():
            raise ValueError("result_id, rule, and explanation cannot be blank")
        if self.amount_difference is not None and self.amount_difference < 0:
            raise ValueError("amount_difference cannot be negative")

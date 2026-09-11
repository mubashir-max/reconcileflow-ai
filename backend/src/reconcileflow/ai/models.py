"""Validated domain values used by AI match suggestions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MatchSuggestionStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class CandidateRecordSet:
    """Internal record identifiers proposed as one advisory match."""

    bank_record_ids: tuple[str, ...] = ()
    erp_invoice_ids: tuple[str, ...] = ()
    gateway_record_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        groups = (self.bank_record_ids, self.erp_invoice_ids, self.gateway_record_ids)
        if not any(groups):
            raise ValueError("at least one candidate record identifier is required")
        for group in groups:
            if len(group) != len(set(group)):
                raise ValueError("candidate record identifiers must be unique")
            if any(not value.strip() or len(value) > 200 for value in group):
                raise ValueError("candidate record identifiers must be nonblank and at most 200 characters")

"""Deterministic, tenant-scoped candidate generation for advisory inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from enum import StrEnum
from hashlib import sha256
from itertools import combinations
import re
import uuid

from .inference import NormalizedMatchFeatures
from .models import CandidateRecordSet


class CandidateSourceType(StrEnum):
    BANK = "BANK"
    ERP = "ERP"
    GATEWAY = "GATEWAY"


@dataclass(frozen=True, slots=True)
class CandidateSourceRecord:
    """Internal-only projection used to compare unresolved records locally."""

    organization_id: uuid.UUID
    run_id: uuid.UUID
    source_type: CandidateSourceType
    record_id: str
    amount: Decimal
    effective_date: date
    currency: str
    references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        record_id = self.record_id.strip()
        currency = self.currency.strip().upper()
        if not record_id or len(record_id) > 200:
            raise ValueError("record_id must be nonblank and at most 200 characters")
        if not currency or len(currency) > 3:
            raise ValueError("currency must be a valid short code")
        if not isinstance(self.amount, Decimal):
            raise TypeError("amount must be Decimal")
        if len(self.references) > 20 or any(len(value) > 200 for value in self.references):
            raise ValueError("references exceed the safe local comparison bounds")
        object.__setattr__(self, "record_id", record_id)
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class GeneratedCandidate:
    records: CandidateRecordSet
    features: NormalizedMatchFeatures


class ReconciliationCandidateGenerator:
    """Generate bounded cross-source candidates without network or persistence access."""

    def __init__(
        self, *, maximum_candidates: int = 100, maximum_date_difference_days: int = 30,
        maximum_amount_difference_ratio: Decimal = Decimal("0.25"),
    ) -> None:
        if not 1 <= maximum_candidates <= 1000:
            raise ValueError("maximum_candidates must be between 1 and 1000")
        if not 0 <= maximum_date_difference_days <= 365:
            raise ValueError("maximum_date_difference_days must be between 0 and 365")
        if not Decimal("0") <= maximum_amount_difference_ratio <= Decimal("1"):
            raise ValueError("maximum_amount_difference_ratio must be between 0 and 1")
        self._maximum_candidates = maximum_candidates
        self._maximum_date_difference_days = maximum_date_difference_days
        self._maximum_amount_difference_ratio = maximum_amount_difference_ratio

    def generate(
        self, *, organization_id: uuid.UUID, run_id: uuid.UUID,
        records: tuple[CandidateSourceRecord, ...], excluded_record_ids: frozenset[str] = frozenset(),
    ) -> tuple[GeneratedCandidate, ...]:
        scoped = tuple(
            record for record in records
            if record.organization_id == organization_id
            and record.run_id == run_id
            and record.record_id not in excluded_record_ids
        )
        generated: list[GeneratedCandidate] = []
        seen: set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = set()
        for left, right in combinations(scoped, 2):
            if left.source_type == right.source_type:
                continue
            date_difference = abs((left.effective_date - right.effective_date).days)
            if date_difference > self._maximum_date_difference_days:
                continue
            amount_ratio = _amount_difference_ratio(left.amount, right.amount)
            if amount_ratio > self._maximum_amount_difference_ratio:
                continue
            candidate_set = _candidate_set(left, right)
            identity = (
                candidate_set.bank_record_ids,
                candidate_set.erp_invoice_ids,
                candidate_set.gateway_record_ids,
            )
            if identity in seen:
                continue
            seen.add(identity)
            generated.append(GeneratedCandidate(
                records=candidate_set,
                features=NormalizedMatchFeatures(
                    candidate_reference=_opaque_reference(organization_id, run_id, identity),
                    amount_similarity=float(Decimal("1") - amount_ratio),
                    date_similarity=(
                        1.0 if self._maximum_date_difference_days == 0
                        else round(1 - date_difference / self._maximum_date_difference_days, 6)
                    ),
                    reference_similarity=_reference_similarity(left.references, right.references),
                    currency_matches=left.currency == right.currency,
                ),
            ))
        generated.sort(key=lambda item: (
            -item.features.amount_similarity,
            -item.features.date_similarity,
            -item.features.reference_similarity,
            item.features.candidate_reference,
        ))
        return tuple(generated[: self._maximum_candidates])


def _amount_difference_ratio(left: Decimal, right: Decimal) -> Decimal:
    denominator = max(abs(left), abs(right))
    if denominator == 0:
        return Decimal("0")
    return min(Decimal("1"), abs(left - right) / denominator)


def _normalized_references(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(filter(None, (re.sub(r"[^a-z0-9]", "", value.casefold()) for value in values)))


def _reference_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    normalized_left = _normalized_references(left)
    normalized_right = _normalized_references(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return round(max(
        SequenceMatcher(None, left_value, right_value).ratio()
        for left_value in normalized_left for right_value in normalized_right
    ), 6)


def _candidate_set(left: CandidateSourceRecord, right: CandidateSourceRecord) -> CandidateRecordSet:
    values: dict[CandidateSourceType, list[str]] = {
        CandidateSourceType.BANK: [], CandidateSourceType.ERP: [], CandidateSourceType.GATEWAY: [],
    }
    values[left.source_type].append(left.record_id)
    values[right.source_type].append(right.record_id)
    return CandidateRecordSet(
        bank_record_ids=tuple(sorted(values[CandidateSourceType.BANK])),
        erp_invoice_ids=tuple(sorted(values[CandidateSourceType.ERP])),
        gateway_record_ids=tuple(sorted(values[CandidateSourceType.GATEWAY])),
    )


def _opaque_reference(
    organization_id: uuid.UUID, run_id: uuid.UUID,
    identity: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
) -> str:
    material = "\x1f".join((str(organization_id), str(run_id), *(value for group in identity for value in group)))
    return f"candidate-{sha256(material.encode('utf-8')).hexdigest()}"

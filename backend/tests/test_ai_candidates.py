from datetime import date
from decimal import Decimal
import uuid

import pytest

from reconcileflow.ai import (
    CandidateSourceRecord,
    CandidateSourceType,
    ReconciliationCandidateGenerator,
)
from reconcileflow.api.app import create_app
from reconcileflow.api.config import APISettings


ORGANIZATION_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()


def _record(
    record_id: str, source_type: CandidateSourceType, *,
    organization_id: uuid.UUID = ORGANIZATION_ID, run_id: uuid.UUID = RUN_ID,
    amount: str = "100.00", day: int = 1, currency: str = "USD",
    references: tuple[str, ...] = (),
) -> CandidateSourceRecord:
    return CandidateSourceRecord(
        organization_id=organization_id,
        run_id=run_id,
        source_type=source_type,
        record_id=record_id,
        amount=Decimal(amount),
        effective_date=date(2026, 1, day),
        currency=currency,
        references=references,
    )


def test_candidates_are_deterministic_bounded_and_cross_source():
    generator = ReconciliationCandidateGenerator(maximum_candidates=1)
    records = (
        _record("bank-1", CandidateSourceType.BANK, references=("INV-100",)),
        _record("invoice-1", CandidateSourceType.ERP, references=("inv100",)),
        _record("gateway-1", CandidateSourceType.GATEWAY, amount="101.00"),
    )
    first = generator.generate(organization_id=ORGANIZATION_ID, run_id=RUN_ID, records=records)
    second = generator.generate(organization_id=ORGANIZATION_ID, run_id=RUN_ID, records=records)
    assert first == second
    assert len(first) == 1
    assert first[0].records.bank_record_ids == ("bank-1",)
    assert first[0].records.erp_invoice_ids == ("invoice-1",)
    assert first[0].features.reference_similarity == 1.0


def test_candidates_enforce_tenant_run_and_exclusion_boundaries():
    other_organization = uuid.uuid4()
    other_run = uuid.uuid4()
    records = (
        _record("bank-1", CandidateSourceType.BANK),
        _record("excluded", CandidateSourceType.ERP),
        _record("other-tenant", CandidateSourceType.ERP, organization_id=other_organization),
        _record("other-run", CandidateSourceType.ERP, run_id=other_run),
    )
    generated = ReconciliationCandidateGenerator().generate(
        organization_id=ORGANIZATION_ID,
        run_id=RUN_ID,
        records=records,
        excluded_record_ids=frozenset({"excluded"}),
    )
    assert generated == ()


def test_candidates_prefilter_amount_and_date_differences():
    records = (
        _record("bank-1", CandidateSourceType.BANK),
        _record("amount-far", CandidateSourceType.ERP, amount="200.00"),
        _record("date-far", CandidateSourceType.ERP, day=20),
    )
    generator = ReconciliationCandidateGenerator(
        maximum_date_difference_days=5,
        maximum_amount_difference_ratio=Decimal("0.10"),
    )
    assert generator.generate(
        organization_id=ORGANIZATION_ID, run_id=RUN_ID, records=records
    ) == ()


def test_inference_features_do_not_contain_raw_references_or_financial_values():
    secret_reference = "customer-private-invoice-123"
    records = (
        _record("bank-1", CandidateSourceType.BANK, references=(secret_reference,)),
        _record("invoice-1", CandidateSourceType.ERP, references=(secret_reference,)),
    )
    candidate = ReconciliationCandidateGenerator().generate(
        organization_id=ORGANIZATION_ID, run_id=RUN_ID, records=records
    )[0]
    serialized_features = repr(candidate.features)
    assert secret_reference not in serialized_features
    assert "100.00" not in serialized_features
    assert str(ORGANIZATION_ID) not in serialized_features
    assert str(RUN_ID) not in serialized_features


def test_duplicate_record_pairs_are_removed():
    duplicate = _record("bank-1", CandidateSourceType.BANK)
    records = (duplicate, duplicate, _record("invoice-1", CandidateSourceType.ERP))
    generated = ReconciliationCandidateGenerator().generate(
        organization_id=ORGANIZATION_ID, run_id=RUN_ID, records=records
    )
    assert len(generated) == 1


def test_application_constructs_configured_candidate_generator():
    app = create_app(APISettings(
        environment="test",
        ai_max_candidates_per_request=2,
        ai_max_suggestions_per_response=2,
        ai_candidate_max_date_difference_days=5,
        ai_candidate_max_amount_difference_ratio=Decimal("0.10"),
        _env_file=None,
    ))
    assert isinstance(app.state.ai_candidate_generator, ReconciliationCandidateGenerator)


@pytest.mark.parametrize("maximum_candidates", (0, 1001))
def test_invalid_candidate_bounds_are_rejected(maximum_candidates):
    with pytest.raises(ValueError, match="maximum_candidates"):
        ReconciliationCandidateGenerator(maximum_candidates=maximum_candidates)

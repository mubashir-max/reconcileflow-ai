from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reconcileflow.persistence import Base, OrganizationMembershipRecord, OrganizationRecord, UserRecord


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session
    engine.dispose()


def test_organization_user_and_membership_relationships(session: Session) -> None:
    organization = OrganizationRecord(name="Acme Finance", slug="acme-finance")
    user = UserRecord(email="owner@example.com", password_hash="hashed-secret", display_name="Owner")
    membership = OrganizationMembershipRecord(role="OWNER", user=user)
    organization.memberships.append(membership)
    session.add(organization)
    session.commit()

    assert organization.is_active is True
    assert user.is_active is True
    assert membership.is_active is True
    assert membership.organization is organization
    assert user.memberships == [membership]


@pytest.mark.parametrize(
    ("record", "field"),
    [
        (UserRecord(email="MixedCase@example.com", password_hash="hash"), "email"),
        (UserRecord(email="not-an-email", password_hash="hash"), "email"),
        (OrganizationRecord(name="Example", slug="Has Space"), "slug"),
    ],
)
def test_normalized_identity_values_are_required(session: Session, record: object, field: str) -> None:
    session.add(record)
    with pytest.raises(IntegrityError):
        session.commit()


def test_membership_role_and_uniqueness_are_enforced(session: Session) -> None:
    organization = OrganizationRecord(name="Acme", slug="acme")
    user = UserRecord(email="analyst@example.com", password_hash="hash")
    organization.memberships.extend([
        OrganizationMembershipRecord(user=user, role="ANALYST"),
        OrganizationMembershipRecord(user=user, role="VIEWER"),
    ])
    session.add(organization)
    with pytest.raises(IntegrityError):
        session.commit()


def test_unknown_membership_role_is_rejected(session: Session) -> None:
    organization = OrganizationRecord(name="Acme", slug="acme")
    user = UserRecord(email="user@example.com", password_hash="hash")
    organization.memberships.append(OrganizationMembershipRecord(user=user, role="SUPERUSER"))
    session.add(organization)
    with pytest.raises(IntegrityError):
        session.commit()


def test_plaintext_password_column_does_not_exist() -> None:
    columns = set(UserRecord.__table__.columns.keys())
    assert "password_hash" in columns
    assert "password" not in columns

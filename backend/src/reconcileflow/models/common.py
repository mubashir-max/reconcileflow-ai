"""Shared validation helpers for financial domain models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping


def require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return require_text(value, field_name)


def require_currency(value: str, field_name: str = "currency") -> str:
    currency = require_text(value, field_name)
    if len(currency) != 3 or not currency.isascii() or not currency.isalpha() or not currency.isupper():
        raise ValueError(f"{field_name} must be a three-letter uppercase ISO 4217 code")
    return currency


def require_decimal(
    value: Decimal,
    field_name: str,
    *,
    allow_negative: bool = False,
    allow_zero: bool = True,
) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be Decimal, not {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if not allow_negative and value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    if not allow_zero and value == 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return value


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value


def require_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be date")
    return value


def immutable_extra_data(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise TypeError("extra_data must be a mapping")
    return MappingProxyType(dict(value))

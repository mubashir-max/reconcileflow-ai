"""Normalized bank transaction model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from .common import (
    immutable_extra_data,
    optional_text,
    require_aware_datetime,
    require_currency,
    require_date,
    require_decimal,
    require_text,
)
from .enums import BankTransactionStatus, CreditDebitIndicator


@dataclass(frozen=True, slots=True, kw_only=True)
class BankTransaction:
    source_system: str
    source_record_id: str
    transaction_id: str
    account_id: str
    booking_date: date
    amount: Decimal
    currency: str
    credit_debit_indicator: CreditDebitIndicator
    status: BankTransactionStatus
    description: str
    ingested_at: datetime
    statement_id: str | None = None
    entry_reference: str | None = None
    account_servicer_reference: str | None = None
    end_to_end_id: str | None = None
    instruction_id: str | None = None
    mandate_id: str | None = None
    check_number: str | None = None
    value_date: date | None = None
    authorized_date: date | None = None
    booking_datetime: datetime | None = None
    authorized_datetime: datetime | None = None
    account_currency: str | None = None
    account_amount: Decimal | None = None
    exchange_rate: Decimal | None = None
    transaction_code: str | None = None
    payment_channel: str | None = None
    category: str | None = None
    subcategory: str | None = None
    original_description: str | None = None
    remittance_information: str | None = None
    merchant_name: str | None = None
    merchant_category_code: str | None = None
    counterparty_name: str | None = None
    counterparty_account_id: str | None = None
    counterparty_iban_masked: str | None = None
    counterparty_bic: str | None = None
    counterparty_country: str | None = None
    debtor_name: str | None = None
    creditor_name: str | None = None
    invoice_reference: str | None = None
    customer_reference: str | None = None
    bank_reference: str | None = None
    balance_after_transaction: Decimal | None = None
    branch_id: str | None = None
    location_country: str | None = None
    location_city: str | None = None
    is_fee: bool = False
    is_reversal: bool = False
    reversal_of_transaction_id: str | None = None
    extra_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_system", "source_record_id", "transaction_id", "account_id", "description"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(self, "currency", require_currency(self.currency))
        object.__setattr__(self, "amount", require_decimal(self.amount, "amount", allow_zero=False))
        object.__setattr__(self, "ingested_at", require_aware_datetime(self.ingested_at, "ingested_at"))

        require_date(self.booking_date, "booking_date")
        if not isinstance(self.credit_debit_indicator, CreditDebitIndicator):
            raise TypeError("credit_debit_indicator must be CreditDebitIndicator")
        if not isinstance(self.status, BankTransactionStatus):
            raise TypeError("status must be BankTransactionStatus")
        if not isinstance(self.is_fee, bool) or not isinstance(self.is_reversal, bool):
            raise TypeError("is_fee and is_reversal must be bool")

        for name in ("booking_datetime", "authorized_datetime"):
            value = getattr(self, name)
            if value is not None:
                require_aware_datetime(value, name)
        for name in ("value_date", "authorized_date"):
            value = getattr(self, name)
            if value is not None:
                require_date(value, name)
        for name in ("account_amount", "exchange_rate"):
            value = getattr(self, name)
            if value is not None:
                require_decimal(value, name, allow_zero=name != "exchange_rate")
        if self.balance_after_transaction is not None:
            require_decimal(self.balance_after_transaction, "balance_after_transaction", allow_negative=True)
        if self.account_currency is not None:
            object.__setattr__(self, "account_currency", require_currency(self.account_currency, "account_currency"))
        if self.is_reversal and self.reversal_of_transaction_id is None:
            raise ValueError("reversal_of_transaction_id is required for a reversal")
        if self.reversal_of_transaction_id is not None:
            object.__setattr__(
                self,
                "reversal_of_transaction_id",
                optional_text(self.reversal_of_transaction_id, "reversal_of_transaction_id"),
            )
        object.__setattr__(self, "extra_data", immutable_extra_data(self.extra_data))

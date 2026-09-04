"""Normalized payment-gateway settlement model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping

from .common import (
    immutable_extra_data,
    require_aware_datetime,
    require_currency,
    require_date,
    require_decimal,
    require_text,
)
from .enums import GatewayStatus, GatewayTransactionType


@dataclass(frozen=True, slots=True, kw_only=True)
class GatewaySettlementEntry:
    source_system: str
    source_record_id: str
    settlement_id: str
    gateway_payment_id: str
    merchant_account_id: str
    transaction_type: GatewayTransactionType
    status: GatewayStatus
    created_at: datetime
    settlement_date: date
    gross_amount: Decimal
    fee_amount: Decimal
    tax_on_fee_amount: Decimal
    refund_amount: Decimal
    chargeback_amount: Decimal
    adjustment_amount: Decimal
    net_amount: Decimal
    currency: str
    settlement_currency: str
    ingested_at: datetime
    available_on: date | None = None
    exchange_rate: Decimal | None = None
    customer_id: str | None = None
    customer_name: str | None = None
    invoice_reference: str | None = None
    order_reference: str | None = None
    gateway_reference: str | None = None
    bank_reference: str | None = None
    payment_method_type: str | None = None
    card_brand: str | None = None
    card_last4: str | None = None
    description: str | None = None
    extra_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "source_system", "source_record_id", "settlement_id",
            "gateway_payment_id", "merchant_account_id",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not isinstance(self.transaction_type, GatewayTransactionType):
            raise TypeError("transaction_type must be GatewayTransactionType")
        if not isinstance(self.status, GatewayStatus):
            raise TypeError("status must be GatewayStatus")
        object.__setattr__(self, "currency", require_currency(self.currency))
        object.__setattr__(
            self,
            "settlement_currency",
            require_currency(self.settlement_currency, "settlement_currency"),
        )
        require_aware_datetime(self.created_at, "created_at")
        require_aware_datetime(self.ingested_at, "ingested_at")
        require_date(self.settlement_date, "settlement_date")
        if self.available_on is not None:
            require_date(self.available_on, "available_on")

        for name in (
            "gross_amount", "fee_amount", "tax_on_fee_amount", "refund_amount", "chargeback_amount",
        ):
            require_decimal(getattr(self, name), name)
        require_decimal(self.adjustment_amount, "adjustment_amount", allow_negative=True)
        require_decimal(self.net_amount, "net_amount", allow_negative=True)
        if self.exchange_rate is not None:
            require_decimal(self.exchange_rate, "exchange_rate", allow_zero=False)

        calculated_net = (
            self.gross_amount
            - self.fee_amount
            - self.tax_on_fee_amount
            - self.refund_amount
            - self.chargeback_amount
            + self.adjustment_amount
        )
        if self.net_amount != calculated_net:
            raise ValueError("net_amount is inconsistent with gross, fees, refunds, chargebacks, and adjustment")
        if self.currency != self.settlement_currency and self.exchange_rate is None:
            raise ValueError("exchange_rate is required for cross-currency settlements")
        if self.card_last4 is not None and (len(self.card_last4) != 4 or not self.card_last4.isdigit()):
            raise ValueError("card_last4 must contain exactly four digits")
        object.__setattr__(self, "extra_data", immutable_extra_data(self.extra_data))

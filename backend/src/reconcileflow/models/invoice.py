"""Normalized ERP invoice and invoice-line models."""

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
from .enums import InvoiceStatus, InvoiceType


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceLine:
    line_id: str
    line_number: int
    item_description: str
    quantity: Decimal
    unit_price: Decimal
    line_net_amount: Decimal
    tax_rate: Decimal
    tax_amount: Decimal
    line_gross_amount: Decimal
    item_id: str | None = None
    unit_code: str | None = None
    line_discount_amount: Decimal = Decimal("0")
    line_charge_amount: Decimal = Decimal("0")
    tax_category: str | None = None
    extra_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "line_id", require_text(self.line_id, "line_id"))
        object.__setattr__(self, "item_description", require_text(self.item_description, "item_description"))
        if isinstance(self.line_number, bool) or not isinstance(self.line_number, int) or self.line_number < 1:
            raise ValueError("line_number must be a positive integer")
        for name in (
            "quantity", "unit_price", "line_net_amount", "tax_rate", "tax_amount",
            "line_gross_amount", "line_discount_amount", "line_charge_amount",
        ):
            require_decimal(getattr(self, name), name)
        if self.quantity == 0:
            raise ValueError("quantity must be greater than zero")

        calculated_net = self.quantity * self.unit_price - self.line_discount_amount + self.line_charge_amount
        if self.line_net_amount != calculated_net:
            raise ValueError("line_net_amount does not equal quantity * unit_price - discount + charge")
        if self.line_gross_amount != self.line_net_amount + self.tax_amount:
            raise ValueError("line_gross_amount does not equal line_net_amount + tax_amount")
        object.__setattr__(self, "extra_data", immutable_extra_data(self.extra_data))


@dataclass(frozen=True, slots=True, kw_only=True)
class ERPInvoice:
    source_system: str
    source_record_id: str
    invoice_id: str
    invoice_number: str
    invoice_type: InvoiceType
    status: InvoiceStatus
    issue_date: date
    currency: str
    supplier_id: str
    supplier_name: str
    customer_id: str
    customer_name: str
    document_subtotal: Decimal
    document_discount_amount: Decimal
    document_charge_amount: Decimal
    document_tax_amount: Decimal
    document_total_amount: Decimal
    prepaid_amount: Decimal
    paid_amount: Decimal
    amount_due: Decimal
    lines: tuple[InvoiceLine, ...]
    ingested_at: datetime
    due_date: date | None = None
    service_start_date: date | None = None
    service_end_date: date | None = None
    posting_date: date | None = None
    accounting_period: str | None = None
    tax_currency: str | None = None
    exchange_rate: Decimal | None = None
    purchase_order_reference: str | None = None
    sales_order_reference: str | None = None
    contract_reference: str | None = None
    project_reference: str | None = None
    payment_reference: str | None = None
    supplier_tax_id: str | None = None
    supplier_country: str | None = None
    customer_tax_id: str | None = None
    customer_email: str | None = None
    customer_country: str | None = None
    billing_address_line1: str | None = None
    billing_city: str | None = None
    billing_region: str | None = None
    billing_postal_code: str | None = None
    billing_country: str | None = None
    delivery_address_line1: str | None = None
    delivery_city: str | None = None
    delivery_country: str | None = None
    payment_terms_code: str | None = None
    payment_terms_description: str | None = None
    payment_method: str | None = None
    payment_account_reference: str | None = None
    last_payment_date: date | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    extra_data: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "source_system", "source_record_id", "invoice_id", "invoice_number",
            "supplier_id", "supplier_name", "customer_id", "customer_name",
        ):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(self, "currency", require_currency(self.currency))
        if self.tax_currency is not None:
            object.__setattr__(self, "tax_currency", require_currency(self.tax_currency, "tax_currency"))
        if not isinstance(self.invoice_type, InvoiceType):
            raise TypeError("invoice_type must be InvoiceType")
        if not isinstance(self.status, InvoiceStatus):
            raise TypeError("status must be InvoiceStatus")
        require_date(self.issue_date, "issue_date")
        for name in (
            "due_date", "service_start_date", "service_end_date", "posting_date", "last_payment_date",
        ):
            value = getattr(self, name)
            if value is not None:
                require_date(value, name)
        object.__setattr__(self, "ingested_at", require_aware_datetime(self.ingested_at, "ingested_at"))
        for name in ("created_at", "updated_at"):
            value = getattr(self, name)
            if value is not None:
                require_aware_datetime(value, name)

        for name in (
            "document_subtotal", "document_discount_amount", "document_charge_amount",
            "document_tax_amount", "document_total_amount", "prepaid_amount", "paid_amount", "amount_due",
        ):
            require_decimal(getattr(self, name), name)
        if self.exchange_rate is not None:
            require_decimal(self.exchange_rate, "exchange_rate", allow_zero=False)
        if not isinstance(self.lines, tuple) or not self.lines:
            raise ValueError("lines must be a non-empty tuple of InvoiceLine values")
        if not all(isinstance(line, InvoiceLine) for line in self.lines):
            raise TypeError("lines must contain only InvoiceLine values")
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("invoice line IDs must be unique")

        if sum((line.line_net_amount for line in self.lines), Decimal("0")) != self.document_subtotal:
            raise ValueError("document_subtotal does not equal the sum of invoice line net amounts")
        if sum((line.tax_amount for line in self.lines), Decimal("0")) != self.document_tax_amount:
            raise ValueError("document_tax_amount does not equal the sum of invoice line tax amounts")
        calculated_total = (
            self.document_subtotal
            - self.document_discount_amount
            + self.document_charge_amount
            + self.document_tax_amount
        )
        if self.document_total_amount != calculated_total:
            raise ValueError("document_total_amount is inconsistent with subtotal, discounts, charges, and tax")
        if self.amount_due != self.document_total_amount - self.prepaid_amount - self.paid_amount:
            raise ValueError("amount_due is inconsistent with total, prepaid, and paid amounts")
        object.__setattr__(self, "extra_data", immutable_extra_data(self.extra_data))

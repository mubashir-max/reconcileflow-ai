"""Controlled vocabulary for the ReconcileFlow financial domain."""

from enum import StrEnum


class CreditDebitIndicator(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class BankTransactionStatus(StrEnum):
    BOOKED = "BOOKED"
    PENDING = "PENDING"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class InvoiceType(StrEnum):
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"
    PROFORMA = "PROFORMA"


class InvoiceStatus(StrEnum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"
    OVERDUE = "OVERDUE"


class GatewayTransactionType(StrEnum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"
    CHARGEBACK = "CHARGEBACK"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"
    RESERVE = "RESERVE"


class GatewayStatus(StrEnum):
    PENDING = "PENDING"
    AVAILABLE = "AVAILABLE"
    PAID = "PAID"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class ReconciliationStatus(StrEnum):
    EXACT_MATCH = "EXACT_MATCH"
    SETTLEMENT_MATCH = "SETTLEMENT_MATCH"
    TOLERANCE_MATCH = "TOLERANCE_MATCH"
    MANY_TO_ONE_MATCH = "MANY_TO_ONE_MATCH"
    ONE_TO_MANY_MATCH = "ONE_TO_MANY_MATCH"
    DUPLICATE = "DUPLICATE"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"

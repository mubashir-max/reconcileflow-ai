"""Priority-ordered, deterministic financial reconciliation engine."""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from decimal import Decimal
from typing import Iterable

from reconcileflow.models import (
    BankTransaction,
    BankTransactionStatus,
    CreditDebitIndicator,
    ERPInvoice,
    GatewaySettlementEntry,
    GatewayStatus,
    ReconciliationStatus,
)

from .config import ReconciliationConfig
from .results import ReconciliationResult


def _references(bank: BankTransaction) -> set[str]:
    values = (
        bank.invoice_reference,
        bank.customer_reference,
        bank.end_to_end_id,
        bank.remittance_information,
        bank.description,
    )
    return {value.casefold() for value in values if value}


def _mentions(bank: BankTransaction, invoice: ERPInvoice) -> bool:
    needles = {invoice.invoice_id.casefold(), invoice.invoice_number.casefold()}
    if invoice.payment_reference:
        needles.add(invoice.payment_reference.casefold())
    return any(needle in reference for needle in needles for reference in _references(bank))


def _eligible(bank: BankTransaction) -> bool:
    return (
        bank.status is BankTransactionStatus.BOOKED
        and bank.credit_debit_indicator is CreditDebitIndicator.CREDIT
        and not bank.is_reversal
    )


def _within_days(bank: BankTransaction, invoice: ERPInvoice, days: int) -> bool:
    comparison_date = invoice.due_date or invoice.issue_date
    return abs((bank.booking_date - comparison_date).days) <= days


class ReconciliationEngine:
    """Reconcile typed records once, in a stable and explainable priority order."""

    def __init__(self, config: ReconciliationConfig | None = None) -> None:
        self.config = config or ReconciliationConfig()

    def reconcile(
        self,
        bank_transactions: Iterable[BankTransaction],
        invoices: Iterable[ERPInvoice],
        gateway_entries: Iterable[GatewaySettlementEntry] = (),
    ) -> list[ReconciliationResult]:
        banks = sorted(bank_transactions, key=lambda item: (item.booking_date, item.source_record_id))
        erp = sorted(invoices, key=lambda item: (item.issue_date, item.invoice_id))
        gateways = sorted(gateway_entries, key=lambda item: (item.settlement_date, item.source_record_id))
        self._validate_unique_source_ids(banks, erp, gateways)
        used_banks: set[str] = set()
        used_invoices: set[str] = set()
        used_gateways: set[str] = set()
        results: list[ReconciliationResult] = []

        def add(**values: object) -> None:
            results.append(ReconciliationResult(result_id=f"RESULT-{len(results) + 1:04d}", **values))

        # 1. Duplicates are quarantined before any payment can be consumed.
        duplicate_groups: dict[tuple[object, ...], list[BankTransaction]] = defaultdict(list)
        for bank in banks:
            fingerprint = (bank.transaction_id, bank.bank_reference, bank.booking_date, bank.currency, bank.amount)
            duplicate_groups[fingerprint].append(bank)
        for group in sorted(duplicate_groups.values(), key=lambda values: values[0].source_record_id):
            if len(group) < 2:
                continue
            linked = [invoice for invoice in erp if invoice.invoice_id not in used_invoices and any(_mentions(bank, invoice) and _within_days(bank, invoice, self.config.date_tolerance_days) for bank in group)]
            used_banks.update(bank.source_record_id for bank in group)
            used_invoices.update(invoice.invoice_id for invoice in linked)
            add(
                status=ReconciliationStatus.DUPLICATE,
                rule="DUPLICATE_BANK_FINGERPRINT",
                bank_source_record_ids=tuple(bank.source_record_id for bank in group),
                erp_invoice_ids=tuple(invoice.invoice_id for invoice in linked),
                expected_amount=group[0].amount,
                actual_amount=group[0].amount,
                amount_difference=Decimal("0"),
                currency=group[0].currency,
                explanation="Bank entries share the same transaction ID, bank reference, booking date, currency, and amount.",
                requires_review=True,
            )

        # 2. Exact invoice-to-bank matches.
        for invoice in erp:
            if invoice.invoice_id in used_invoices:
                continue
            candidates = [bank for bank in banks if bank.source_record_id not in used_banks and _eligible(bank) and bank.currency == invoice.currency and bank.amount == invoice.amount_due and _mentions(bank, invoice) and _within_days(bank, invoice, self.config.date_tolerance_days)]
            if len(candidates) == 1:
                bank = candidates[0]
                used_banks.add(bank.source_record_id)
                used_invoices.add(invoice.invoice_id)
                add(status=ReconciliationStatus.EXACT_MATCH, rule="EXACT_REFERENCE_AMOUNT_CURRENCY", bank_source_record_ids=(bank.source_record_id,), erp_invoice_ids=(invoice.invoice_id,), expected_amount=invoice.amount_due, actual_amount=bank.amount, amount_difference=Decimal("0"), currency=invoice.currency, explanation="Invoice reference, currency, and amount match exactly.")

        # 3. Gateway net payouts match bank deposits while gross links the invoice.
        settlement_groups: dict[str, list[GatewaySettlementEntry]] = defaultdict(list)
        for gateway in gateways:
            if gateway.source_record_id not in used_gateways:
                settlement_groups[gateway.settlement_id].append(gateway)
        for settlement_id, group in sorted(settlement_groups.items()):
            net = sum((entry.net_amount for entry in group), Decimal("0"))
            gross = sum((entry.gross_amount for entry in group), Decimal("0"))
            currency = group[0].settlement_currency
            bank_candidates = [bank for bank in banks if bank.source_record_id not in used_banks and _eligible(bank) and bank.currency == currency and bank.amount == net and any(entry.bank_reference and entry.bank_reference == bank.bank_reference and abs((bank.booking_date - entry.settlement_date).days) <= self.config.date_tolerance_days for entry in group)]
            if len(bank_candidates) != 1:
                continue
            bank = bank_candidates[0]
            linked = [invoice for invoice in erp if invoice.invoice_id not in used_invoices and invoice.currency == group[0].currency and invoice.amount_due == gross and any(entry.invoice_reference in {invoice.invoice_id, invoice.invoice_number, invoice.payment_reference} for entry in group)]
            used_banks.add(bank.source_record_id)
            used_gateways.update(entry.source_record_id for entry in group)
            used_invoices.update(invoice.invoice_id for invoice in linked)
            fees = gross - net
            add(status=ReconciliationStatus.SETTLEMENT_MATCH, rule="GATEWAY_NET_TO_BANK", bank_source_record_ids=(bank.source_record_id,), erp_invoice_ids=tuple(invoice.invoice_id for invoice in linked), gateway_source_record_ids=tuple(entry.source_record_id for entry in group), expected_amount=net, actual_amount=bank.amount, amount_difference=abs(bank.amount - net), currency=currency, explanation=f"Gateway gross amount {gross} less fees/refunds/adjustments of {fees} equals bank payout {net}.")

        # 4. Referenced payments inside the configured tolerance.
        for invoice in erp:
            if invoice.invoice_id in used_invoices:
                continue
            candidates = [bank for bank in banks if bank.source_record_id not in used_banks and _eligible(bank) and bank.currency == invoice.currency and Decimal("0") < abs(bank.amount - invoice.amount_due) <= self.config.amount_tolerance and _mentions(bank, invoice) and _within_days(bank, invoice, self.config.date_tolerance_days)]
            if len(candidates) == 1:
                bank = candidates[0]
                difference = abs(bank.amount - invoice.amount_due)
                used_banks.add(bank.source_record_id)
                used_invoices.add(invoice.invoice_id)
                add(status=ReconciliationStatus.TOLERANCE_MATCH, rule="REFERENCE_AMOUNT_TOLERANCE", bank_source_record_ids=(bank.source_record_id,), erp_invoice_ids=(invoice.invoice_id,), expected_amount=invoice.amount_due, actual_amount=bank.amount, amount_difference=difference, currency=invoice.currency, explanation=f"Reference and currency match; amount difference {difference} is within tolerance {self.config.amount_tolerance}.")

        # 5. Multiple explicitly referenced invoices paid by one bank entry.
        for bank in banks:
            if bank.source_record_id in used_banks or not _eligible(bank):
                continue
            candidates = [invoice for invoice in erp if invoice.invoice_id not in used_invoices and invoice.currency == bank.currency and _mentions(bank, invoice) and _within_days(bank, invoice, self.config.date_tolerance_days)]
            chosen = self._matching_combination(candidates, bank.amount)
            if chosen:
                used_banks.add(bank.source_record_id)
                used_invoices.update(invoice.invoice_id for invoice in chosen)
                add(status=ReconciliationStatus.MANY_TO_ONE_MATCH, rule="MULTIPLE_INVOICES_TO_BANK", bank_source_record_ids=(bank.source_record_id,), erp_invoice_ids=tuple(invoice.invoice_id for invoice in chosen), expected_amount=sum((invoice.amount_due for invoice in chosen), Decimal("0")), actual_amount=bank.amount, amount_difference=Decimal("0"), currency=bank.currency, explanation="Multiple referenced invoices total the single bank payment exactly.")

        # 6. One invoice paid by multiple explicitly referenced bank entries.
        for invoice in erp:
            if invoice.invoice_id in used_invoices:
                continue
            candidates = [bank for bank in banks if bank.source_record_id not in used_banks and _eligible(bank) and bank.currency == invoice.currency and _mentions(bank, invoice) and _within_days(bank, invoice, self.config.date_tolerance_days)]
            chosen_banks = self._matching_bank_combination(candidates, invoice.amount_due)
            if chosen_banks:
                used_banks.update(bank.source_record_id for bank in chosen_banks)
                used_invoices.add(invoice.invoice_id)
                add(status=ReconciliationStatus.ONE_TO_MANY_MATCH, rule="INVOICE_TO_MULTIPLE_BANK_PAYMENTS", bank_source_record_ids=tuple(bank.source_record_id for bank in chosen_banks), erp_invoice_ids=(invoice.invoice_id,), expected_amount=invoice.amount_due, actual_amount=sum((bank.amount for bank in chosen_banks), Decimal("0")), amount_difference=Decimal("0"), currency=invoice.currency, explanation="Multiple referenced bank payments total the invoice amount exactly.")

        # 7. Gateway funds without a booked bank payout require review.
        for settlement_id, group in sorted(settlement_groups.items()):
            remaining = [entry for entry in group if entry.source_record_id not in used_gateways]
            if not remaining:
                continue
            used_gateways.update(entry.source_record_id for entry in remaining)
            linked = [invoice for invoice in erp if invoice.invoice_id not in used_invoices and any(entry.invoice_reference in {invoice.invoice_id, invoice.invoice_number, invoice.payment_reference} for entry in remaining)]
            used_invoices.update(invoice.invoice_id for invoice in linked)
            amount = sum((entry.net_amount for entry in remaining), Decimal("0"))
            add(status=ReconciliationStatus.REQUIRES_REVIEW, rule="GATEWAY_AWAITING_BANK_SETTLEMENT", erp_invoice_ids=tuple(invoice.invoice_id for invoice in linked), gateway_source_record_ids=tuple(entry.source_record_id for entry in remaining), expected_amount=amount, actual_amount=None, amount_difference=None, currency=remaining[0].settlement_currency, explanation="Gateway funds are available or paid, but no corresponding booked bank payout was found.", requires_review=True)

        # 8. Anything left remains visible rather than silently disappearing.
        for bank in banks:
            if bank.source_record_id not in used_banks:
                add(status=ReconciliationStatus.REQUIRES_REVIEW, rule="UNMATCHED_BANK_TRANSACTION", bank_source_record_ids=(bank.source_record_id,), expected_amount=None, actual_amount=bank.amount, amount_difference=None, currency=bank.currency, explanation="No eligible invoice or gateway settlement matched this bank transaction.", requires_review=True)
        for invoice in erp:
            if invoice.invoice_id not in used_invoices:
                add(status=ReconciliationStatus.REQUIRES_REVIEW, rule="UNMATCHED_ERP_INVOICE", erp_invoice_ids=(invoice.invoice_id,), expected_amount=invoice.amount_due, actual_amount=None, amount_difference=None, currency=invoice.currency, explanation="No eligible bank payment or gateway settlement matched this invoice.", requires_review=True)
        return results

    def _matching_combination(self, invoices: list[ERPInvoice], target: Decimal) -> tuple[ERPInvoice, ...]:
        for size in range(2, min(len(invoices), self.config.maximum_group_size) + 1):
            matches = [group for group in combinations(invoices, size) if sum((item.amount_due for item in group), Decimal("0")) == target]
            if len(matches) == 1:
                return matches[0]
        return ()

    def _matching_bank_combination(self, banks: list[BankTransaction], target: Decimal) -> tuple[BankTransaction, ...]:
        for size in range(2, min(len(banks), self.config.maximum_group_size) + 1):
            matches = [group for group in combinations(banks, size) if sum((item.amount for item in group), Decimal("0")) == target]
            if len(matches) == 1:
                return matches[0]
        return ()

    @staticmethod
    def _validate_unique_source_ids(banks: list[BankTransaction], invoices: list[ERPInvoice], gateways: list[GatewaySettlementEntry]) -> None:
        for label, identifiers in (
            ("bank", [item.source_record_id for item in banks]),
            ("invoice", [item.invoice_id for item in invoices]),
            ("gateway", [item.source_record_id for item in gateways]),
        ):
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{label} input contains duplicate canonical source IDs")

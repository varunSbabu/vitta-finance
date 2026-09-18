"""PhonePe PDF statement parser.

PhonePe statements have spaced, readable text (unlike GPay's concatenated
format).  Each transaction is a multi-line block:

    Aug 20, 2026 Received from mamtha bk Credit INR 5500.00
    08:03 AM Transaction ID : T2608200803106086138274
    UTR No : 938597085836
    Credited to Account

Edge cases handled:
- Amount wraps to the next line (large amounts)
- "Cashback Received" entries have no UTR line
- Transaction IDs starting with "T" or "AC"
- Password-protected PDFs (decrypted via pikepdf)
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)

# ── regex patterns ──────────────────────────────────────────────────────────

# First line of a transaction block:
#   Aug 20, 2026 Received from mamtha bk Credit INR 5500.00
# The amount after "INR" may be absent when it wraps to the next line.
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
TXN_LINE = re.compile(
    rf"^({_MONTHS}\s+\d{{1,2}},\s+\d{{4}})\s+"
    r"(Paid to|Received from|Cashback Received)\s+"
    r"(?:(.+?)\s+)?"
    r"(Credit|Debit)\s+"
    r"INR\s*"
    r"([\d,]+(?:\.\d{1,2})?)?$"
)

# Time + Transaction ID line, with optional wrapped amount at end:
#   08:03 AM Transaction ID : T2608200803106086138274
#   06:56 PM Transaction ID : T2608201856373468196151 10000.00
TIME_LINE = re.compile(
    r"^(\d{1,2}:\d{2}\s+[APap][Mm])\s+"
    r"Transaction ID\s*:\s*([A-Za-z0-9]+)"
    r"(?:\s+([\d,]+(?:\.\d{1,2})?))?$"
)

# UTR reference line (absent for cashback transactions)
UTR_LINE = re.compile(r"^UTR No\s*:\s*(\d+)$")

# Account / source line
ACCT_LINE = re.compile(r"^(Credited to|Debited from)\s+(.+)$")

# Lines to skip
HEADER_LINE = re.compile(r"^Date\s+Transaction Details\s+Type\s+Amount$")
PAGE_LINE = re.compile(r"^Page\s+\d+\s+of\s+\d+")
STMT_HEADER = re.compile(r"^Transaction Statement for")
DATE_RANGE = re.compile(
    rf"^{_MONTHS}\s+\d{{1,2}},\s+\d{{4}}\s*-\s*"
    rf"{_MONTHS}\s+\d{{1,2}},\s+\d{{4}}$"
)


# ── dataclass ───────────────────────────────────────────────────────────────


@dataclass
class PhonePeTxn:
    date: str
    time: str
    direction: str
    merchant_raw: str
    merchant: str
    amount: float
    upi_ref: str
    bank_name: str
    account_last4: str
    source: str = "phonepe_pdf"

    def to_dict(self):
        return asdict(self)


# ── helpers ─────────────────────────────────────────────────────────────────


def _parse_date(raw: str) -> Optional[str]:
    """Parse 'Aug 20, 2026' to ISO date string."""
    try:
        return datetime.strptime(raw.strip(), "%b %d, %Y").date().isoformat()
    except ValueError:
        return None


def _clean_merchant(raw: str) -> str:
    """Normalise merchant name: collapse whitespace."""
    if not raw:
        return raw
    return re.sub(r"\s+", " ", raw).strip()


def _parse_account_detail(detail: str):
    """Return (bank_name, account_last4) from the text after Credited to / Debited from."""
    detail = detail.strip()
    if detail == "Account":
        return "PhonePe", ""
    if detail == "Gift Card":
        return "PhonePe Gift Card", ""
    if detail == "Wallet":
        return "PhonePe Wallet", ""
    m = re.match(r"^XX(\d+)$", detail)
    if m:
        return "PhonePe", m.group(1)
    # Fallback for unknown patterns
    return "PhonePe", ""


def _is_skip_line(line: str) -> bool:
    """Return True for header / footer / non-transaction lines."""
    return bool(
        HEADER_LINE.match(line) or PAGE_LINE.match(line) or STMT_HEADER.match(line) or DATE_RANGE.match(line)
    )


# ── PDF reading ─────────────────────────────────────────────────────────────


def _iter_lines(path: str, password: Optional[str] = None):
    """Yield stripped non-empty lines from every page of the PDF."""
    tmp_path = None

    if password:
        import pikepdf

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_fd)
        try:
            with pikepdf.open(path, password=password) as pdf:
                pdf.save(tmp_path)
        except Exception:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    read_path = tmp_path or path

    try:
        with pdfplumber.open(read_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                for raw in text.split("\n"):
                    line = raw.strip()
                    if line:
                        yield line
    except Exception as exc:
        if not password and "encrypted" in str(exc).lower():
            raise ValueError("PDF is password-protected") from exc
        raise
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── main parser ─────────────────────────────────────────────────────────────


def parse(path: str, password: Optional[str] = None) -> list[dict]:
    """Parse a PhonePe PDF statement and return a list of transaction dicts."""
    lines = list(_iter_lines(path, password))
    txns: list[PhonePeTxn] = []

    i, n = 0, len(lines)
    while i < n:
        if _is_skip_line(lines[i]):
            i += 1
            continue

        m1 = TXN_LINE.match(lines[i])
        if not m1:
            i += 1
            continue

        date_raw, action, merchant_raw, txn_type, amount_str = m1.groups()
        iso_date = _parse_date(date_raw)
        if not iso_date:
            i += 1
            continue

        # For cashback entries the merchant capture group is empty
        merchant_raw = merchant_raw or ""
        if not merchant_raw and action == "Cashback Received":
            merchant_raw = "Cashback"

        # Next line must be time + transaction ID
        if i + 1 >= n:
            break
        m2 = TIME_LINE.match(lines[i + 1])
        if not m2:
            i += 1
            continue

        time_raw, txn_id, wrapped_amount = m2.groups()

        # Resolve amount: line-1 when present, otherwise the wrapped value
        final_amount_str = amount_str or wrapped_amount
        if not final_amount_str:
            i += 1
            continue

        try:
            amount = float(final_amount_str.replace(",", ""))
        except ValueError:
            i += 1
            continue

        # Look ahead for UTR and account lines
        upi_ref = ""
        bank_name = ""
        account_last4 = ""
        j = i + 2

        if j < n:
            m3 = UTR_LINE.match(lines[j])
            if m3:
                upi_ref = m3.group(1)
                j += 1

        if j < n:
            m4 = ACCT_LINE.match(lines[j])
            if m4:
                bank_name, account_last4 = _parse_account_detail(m4.group(2))
                j += 1

        # Fallback: use transaction ID when UTR is absent (cashback etc.)
        if not upi_ref:
            upi_ref = txn_id

        direction = "credit" if txn_type == "Credit" else "debit"

        txns.append(
            PhonePeTxn(
                date=iso_date,
                time=time_raw.upper(),
                direction=direction,
                merchant_raw=merchant_raw,
                merchant=_clean_merchant(merchant_raw),
                amount=amount,
                upi_ref=upi_ref,
                bank_name=bank_name,
                account_last4=account_last4,
            )
        )

        i = j  # advance past all consumed lines

    return [t.to_dict() for t in txns]

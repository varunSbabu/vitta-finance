"""GPay PDF statement parser.

Google's PDF encoder omits spaces between visually-separated words, so
extract_text() returns lines like:
    '01Jul,2026 PaidtoNagarajC ₹29'
    '08:36AM UPITransactionID:618250019059'
    'PaidbyIndianBank7318'

Each transaction is a 3-line block. This parser walks the lines, groups
them, and extracts date/time/merchant/direction/amount/upi_ref/bank/last4.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)

DATE_LINE = re.compile(
    r"^(\d{2})([A-Z][a-z]{2}),(\d{4})\s+"
    r"(Paidto|Receivedfrom)(.+?)\s+"
    r"₹([\d,]+(?:\.\d{1,2})?)$"
)

TIME_LINE = re.compile(
    r"^(\d{1,2}:\d{2}[APap][Mm])\s+"
    r"UPITransactionID:(\d+)$"
)

BANK_LINE = re.compile(r"^Paid(by|to)(.+?)(\d{3,5})$")


@dataclass
class GPayTxn:
    date: str
    time: str
    direction: str
    merchant_raw: str
    merchant: str
    amount: float
    upi_ref: str
    bank_name: str
    account_last4: str
    source: str = "gpay_pdf"

    def to_dict(self):
        return asdict(self)


def _parse_date(dd: str, mon: str, yyyy: str) -> Optional[str]:
    try:
        return datetime.strptime(f"{dd} {mon} {yyyy}", "%d %b %Y").date().isoformat()
    except ValueError:
        return None


def _clean_time(t: str) -> str:
    m = re.match(r"^(\d{1,2}:\d{2})([APap][Mm])$", t)
    return f"{m.group(1)} {m.group(2).upper()}" if m else t


def _split_case_words(s: str) -> str:
    if not s:
        return s
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_merchant(raw: str) -> str:
    if raw.isupper():
        return raw
    return _split_case_words(raw)


def _clean_bank(raw: str) -> str:
    return _split_case_words(raw)


def _iter_lines(path: str):
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                line = raw.strip()
                if line:
                    yield line


def parse(path: str) -> list[dict]:
    lines = list(_iter_lines(path))
    txns: list[GPayTxn] = []

    i, n = 0, len(lines)
    while i < n:
        m1 = DATE_LINE.match(lines[i])
        if not m1:
            i += 1
            continue

        dd, mon, yyyy, kind, details, amount_str = m1.groups()
        iso_date = _parse_date(dd, mon, yyyy)
        if not iso_date:
            i += 1
            continue

        if i + 1 >= n:
            break
        m2 = TIME_LINE.match(lines[i + 1])
        if not m2:
            i += 1
            continue
        time_raw, upi_ref = m2.groups()

        bank_name = ""
        account_last4 = ""
        if i + 2 < n:
            m3 = BANK_LINE.match(lines[i + 2])
            if m3:
                _, bank_raw, account_last4 = m3.groups()
                bank_name = _clean_bank(bank_raw)

        try:
            amount = float(amount_str.replace(",", ""))
        except ValueError:
            i += 1
            continue

        direction = "debit" if kind == "Paidto" else "credit"

        txns.append(
            GPayTxn(
                date=iso_date,
                time=_clean_time(time_raw),
                direction=direction,
                merchant_raw=details,
                merchant=_clean_merchant(details),
                amount=amount,
                upi_ref=upi_ref,
                bank_name=bank_name,
                account_last4=account_last4,
            )
        )

        i += 3

    return [t.to_dict() for t in txns]

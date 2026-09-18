"""Indian credit card statement PDF parser.

Handles statements from major Indian card issuers (HDFC, ICICI, SBI Card,
Axis, Kotak, RBL, IDFC, IndusInd, etc.). These PDFs typically have a
transaction table with columns:

    Date | Transaction Details/Description | Amount

Key differences from bank account statements:
  - Single "Amount" column (no separate Debit/Credit). Charges are positive,
    payments/refunds are negative or marked with "Cr" suffix.
  - Description contains merchant name + city, not UPI narrations.
  - No UPI ref, VPA, or remark — just merchant names (often in ALL CAPS
    with city/country suffix like "AMAZON IN  BANGALORE IN").
  - Statement also contains summary sections (total due, minimum due,
    reward points) that must be skipped.
  - Some issuers use two columns: "Domestic Transactions" / "International"
    with separate sub-tables.
  - Amounts use Indian format: 1,23,456.78 or just 12345.78.
  - Password protection common (DOB, PAN last 4 + DOB, etc.).

Merchant cleaning:
  CC merchants are messy — "SWIGGY 5.0 BANGALORE IN" or
  "AMAZON.IN NEW DELHI IN" or "UBER INDIA SYSTEMS PRI BLR".
  We strip trailing city/country codes and clean up the merchant name.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

import pdfplumber

logging.getLogger("pdfminer").setLevel(logging.ERROR)


@dataclass
class CCTxn:
    date: str
    time: str
    direction: str
    merchant_raw: str
    merchant: str
    amount: float
    upi_ref: str
    bank_name: str
    account_last4: str
    vpa: str
    remark: str
    txn_type: str
    source: str = "cc_pdf"

    def to_dict(self):
        return asdict(self)


# ── Date formats seen in CC statements ──────────────────────────────
DATE_FORMATS = [
    "%d/%m/%Y",  # 01/07/2026
    "%d-%m-%Y",  # 01-07-2026
    "%d %b %Y",  # 01 Jul 2026
    "%d/%m/%y",  # 01/07/26
    "%d-%m-%y",  # 01-07-26
    "%d %b %y",  # 01 Jul 26
    "%d %b, %Y",  # 01 Jul, 2026
    "%d-%b-%Y",  # 01-Jul-2026
    "%d-%b-%y",  # 01-Jul-26
    "%d %B %Y",  # 01 July 2026
    "%Y-%m-%d",  # 2026-07-01 (ISO)
]


def _parse_date(raw: str) -> Optional[str]:
    raw = raw.strip().replace("  ", " ")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── Amount parsing ──────────────────────────────────────────────────


def _parse_cc_amount(raw: str) -> tuple[Optional[float], str]:
    """Parse a CC statement amount. Returns (abs_amount, direction).

    Positive amounts or no suffix = debit (charge).
    Negative amounts or 'Cr'/'CR' suffix = credit (payment/refund).
    """
    if not raw:
        return None, "debit"
    s = raw.strip()

    # Detect Cr/CR suffix (payment/refund)
    is_credit = False
    if re.search(r"\b[Cc][Rr]\.?\s*$", s):
        is_credit = True
        s = re.sub(r"\s*[Cc][Rr]\.?\s*$", "", s)

    # Detect Dr/DR suffix (charge — explicit)
    s = re.sub(r"\s*[Dd][Rr]\.?\s*$", "", s)

    # Clean currency symbols and formatting
    s = s.replace("₹", "").replace("INR", "").replace("Rs.", "")
    s = s.replace("Rs", "").replace(" ", "").replace(",", "")

    # Handle negative sign
    if s.startswith("-") or s.startswith("("):
        is_credit = True
        s = s.lstrip("-").strip("()")

    s = s.strip()
    if not s:
        return None, "debit"

    try:
        val = float(s)
        if val <= 0:
            return None, "debit"
        direction = "credit" if is_credit else "debit"
        return val, direction
    except ValueError:
        return None, "debit"


# ── Issuer detection ─────────────────────────────────────────────────

ISSUER_PATTERNS = [
    (re.compile(r"HDFC\s*Bank", re.I), "HDFC Bank"),
    (re.compile(r"ICICI\s*Bank", re.I), "ICICI Bank"),
    (re.compile(r"SBI\s*Card", re.I), "SBI Card"),
    (re.compile(r"Axis\s*Bank", re.I), "Axis Bank"),
    (re.compile(r"Kotak\s*(?:Mahindra)?\s*Bank", re.I), "Kotak Mahindra Bank"),
    (re.compile(r"RBL\s*Bank", re.I), "RBL Bank"),
    (re.compile(r"IDFC\s*(?:First)?\s*Bank", re.I), "IDFC First Bank"),
    (re.compile(r"IndusInd\s*Bank", re.I), "IndusInd Bank"),
    (re.compile(r"Yes\s*Bank", re.I), "Yes Bank"),
    (re.compile(r"Standard\s*Chartered", re.I), "Standard Chartered"),
    (re.compile(r"Citi\s*(?:bank)?", re.I), "Citibank"),
    (re.compile(r"HSBC", re.I), "HSBC"),
    (re.compile(r"American\s*Express|AMEX", re.I), "American Express"),
    (re.compile(r"BOB\s*(?:Financial)?|Bank\s*of\s*Baroda", re.I), "Bank of Baroda"),
    (re.compile(r"AU\s*(?:Small\s*Finance)?\s*Bank", re.I), "AU Small Finance Bank"),
    (re.compile(r"Federal\s*Bank", re.I), "Federal Bank"),
]

CARD_NUMBER_RE = re.compile(
    r"(?:Card\s*(?:No\.?|Number|#)\s*:?\s*)"
    r"(?:[X*x]{4}[\s-]?){2,3}(\d{4})",
    re.IGNORECASE,
)
CARD_LAST4_RE = re.compile(r"[X*x]{4,12}[\s-]?(\d{4})")


def _detect_issuer(text_lines: list[str]) -> tuple[str, str]:
    """Detect card issuer and last 4 digits from header area."""
    issuer = ""
    last4 = ""

    for line in text_lines[:40]:
        if not issuer:
            for pattern, name in ISSUER_PATTERNS:
                if pattern.search(line):
                    issuer = name
                    break

        if not last4:
            m = CARD_NUMBER_RE.search(line)
            if m:
                last4 = m.group(1)
            elif not last4:
                m = CARD_LAST4_RE.search(line)
                if m:
                    last4 = m.group(1)

        if issuer and last4:
            break

    return issuer, last4


# ── Merchant cleaning ────────────────────────────────────────────────

# Common city/country suffixes in CC merchant names
_CITY_SUFFIXES = re.compile(
    r"\s+(?:"
    r"(?:BANGALORE|BENGALURU|MUMBAI|DELHI|NEW DELHI|CHENNAI|HYDERABAD|PUNE|"
    r"KOLKATA|AHMEDABAD|GURGAON|GURUGRAM|NOIDA|JAIPUR|LUCKNOW|KOCHI|"
    r"COIMBATORE|MYSORE|MYSURU|MANGALORE|MANGALURU|VIZAG|VISAKHAPATNAM|"
    r"BHOPAL|INDORE|CHANDIGARH|NAGPUR|SURAT|VADODARA|PATNA|RANCHI|"
    r"TRIVANDRUM|THIRUVANANTHAPURAM|MADURAI|SALEM|VELLORE|"
    r"BLR|MUM|DEL|BOM|MAA|HYD|CCU|AMD|GGN|PNQ)"
    r"(?:\s+(?:IN|IND|INDIA))?"
    r"|(?:IN|IND|INDIA)"
    r")\s*$",
    re.IGNORECASE,
)

# Trailing reference/auth numbers
_TRAILING_REF = re.compile(r"\s+\d{6,}$")

# "5.0" version numbers in merchant names (e.g., "SWIGGY 5.0")
_VERSION_NUM = re.compile(r"\s+\d+\.\d+(?:\s|$)")

_SKIP_DESCRIPTIONS = {
    "total",
    "sub total",
    "subtotal",
    "total amount due",
    "minimum amount due",
    "minimum due",
    "opening balance",
    "closing balance",
    "previous balance",
    "payment received",
    "payment - thank you",
    "cr to a/c",
    "finance charge",
    "late payment charge",
    "late payment fee",
    "annual fee",
    "membership fee",
    "reward points",
    "cashback",
    "gst",
    "goods and services tax",
    "tax on interest",
    "interest charged",
    "over limit charge",
    "cess",
    "surcharge",
}

_SKIP_PATTERNS = [
    re.compile(r"^statement\s+(period|date|for)", re.I),
    re.compile(r"^page\s+\d+", re.I),
    re.compile(r"^credit\s+limit", re.I),
    re.compile(r"^available\s+(?:credit|limit)", re.I),
    re.compile(r"^(?:total|minimum)\s+(?:amount\s+)?due", re.I),
    re.compile(r"^payment\s+due\s+date", re.I),
    re.compile(r"^reward\s+points?\s+(?:earned|redeemed|balance)", re.I),
]


def _should_skip(desc: str) -> bool:
    low = desc.strip().lower()
    if low in _SKIP_DESCRIPTIONS:
        return True
    for pat in _SKIP_PATTERNS:
        if pat.search(low):
            return True
    return False


def _clean_cc_merchant(raw: str) -> str:
    """Clean a credit card merchant name."""
    s = raw.strip()
    if not s:
        return s

    # Remove city/country suffix
    s = _CITY_SUFFIXES.sub("", s)
    # Remove trailing reference numbers
    s = _TRAILING_REF.sub("", s)
    # Clean version numbers
    s = _VERSION_NUM.sub(" ", s)
    # Clean up multiple spaces
    s = re.sub(r"\s+", " ", s).strip()
    # Title-case if all upper and reasonably long
    if s.isupper() and len(s) > 3:
        s = s.title()
    # Remove trailing dots/asterisks
    s = s.rstrip(".*").strip()

    return s


# ── Column detection ─────────────────────────────────────────────────

DATE_HEADERS = {"date", "txn date", "transaction date", "trans date", "posting date", "post date"}
DESC_HEADERS = {
    "description",
    "transaction details",
    "details",
    "particulars",
    "narration",
    "transaction description",
    "merchant details",
}
AMOUNT_HEADERS = {"amount", "amt", "transaction amount", "txn amount", "debit/credit", "dr/cr"}
DEBIT_HEADERS = {"debit", "dr", "debit amount"}
CREDIT_HEADERS = {"credit", "cr", "credit amount"}


def _detect_columns(header_row: list[str]) -> dict:
    mapping = {}
    for i, cell in enumerate(header_row):
        h = cell.strip().lower().replace(".", "").replace("  ", " ")
        if h in DATE_HEADERS:
            mapping.setdefault("date", i)
        elif h in DESC_HEADERS:
            mapping.setdefault("desc", i)
        elif h in AMOUNT_HEADERS:
            mapping.setdefault("amount", i)
        elif h in DEBIT_HEADERS:
            mapping.setdefault("debit", i)
        elif h in CREDIT_HEADERS:
            mapping.setdefault("credit", i)
    return mapping


def _find_header_row(rows: list[list[str]]) -> tuple[int, dict]:
    for i, row in enumerate(rows):
        joined = " ".join(c.lower() for c in row if c)
        has_date = any(h in joined for h in DATE_HEADERS)
        has_desc = any(h in joined for h in DESC_HEADERS)
        has_amount = any(h in joined for h in AMOUNT_HEADERS | DEBIT_HEADERS | CREDIT_HEADERS)
        if has_date and (has_desc or has_amount):
            mapping = _detect_columns(row)
            if "date" in mapping and ("amount" in mapping or "debit" in mapping):
                return i, mapping
    return -1, {}


# ── Text-line fallback ───────────────────────────────────────────────
# When pdfplumber can't extract tables, fall back to line-by-line parsing.
# Common format: "01/07/2026  AMAZON IN  BANGALORE IN  1,234.56"

_TEXT_TXN_LINE = re.compile(
    r"^(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+"
    r"(.+?)\s+"
    r"([\-]?(?:₹|INR|Rs\.?)?\s*[\d,]+\.\d{2}\s*(?:Cr|CR|Dr|DR)?)\s*$"
)


def _parse_text_lines(lines: list[str], issuer: str, last4: str) -> list[dict]:
    """Line-by-line fallback parser."""
    txns = []
    for line in lines:
        m = _TEXT_TXN_LINE.match(line.strip())
        if not m:
            continue

        date_str, desc, amount_str = m.group(1), m.group(2).strip(), m.group(3).strip()
        iso_date = _parse_date(date_str)
        if not iso_date:
            continue

        if _should_skip(desc):
            continue

        amount, direction = _parse_cc_amount(amount_str)
        if amount is None:
            continue

        txns.append(
            CCTxn(
                date=iso_date,
                time="",
                direction=direction,
                merchant_raw=desc,
                merchant=_clean_cc_merchant(desc) or desc,
                amount=amount,
                upi_ref="",
                bank_name=issuer,
                account_last4=last4,
                vpa="",
                remark="",
                txn_type="card",
            ).to_dict()
        )

    return txns


# ── Main parse function ──────────────────────────────────────────────


def parse(path: str, password: str | None = None) -> list[dict]:
    """Parse an Indian credit card statement PDF.

    Args:
        path: Path to the PDF file.
        password: Optional password (issuers use DOB, PAN+DOB, etc.).

    Returns:
        List of transaction dicts ready for import.
    """
    open_kwargs = {}
    if password:
        open_kwargs["password"] = password

    with pdfplumber.open(path, **open_kwargs) as pdf:
        text_lines = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            text_lines.extend(text.split("\n"))

        issuer, last4 = _detect_issuer(text_lines)

        # Try table extraction
        all_rows = []
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        all_rows.append([c.strip() if c else "" for c in row])

    if not all_rows:
        return _parse_text_lines(text_lines, issuer, last4)

    header_idx, col_map = _find_header_row(all_rows)
    if header_idx < 0:
        return _parse_text_lines(text_lines, issuer, last4)

    txns = []
    date_col = col_map["date"]
    desc_col = col_map.get("desc")
    amount_col = col_map.get("amount")
    debit_col = col_map.get("debit")
    credit_col = col_map.get("credit")

    for row in all_rows[header_idx + 1 :]:
        if len(row) <= date_col:
            continue

        iso_date = _parse_date(row[date_col])
        if not iso_date:
            continue

        desc = ""
        if desc_col is not None and len(row) > desc_col:
            desc = row[desc_col].strip()
        if not desc:
            continue

        if _should_skip(desc):
            continue

        # Single amount column
        if amount_col is not None and len(row) > amount_col:
            amount, direction = _parse_cc_amount(row[amount_col])
        # Separate debit/credit columns (like bank statements)
        elif debit_col is not None:
            debit_amt, _ = _parse_cc_amount(row[debit_col]) if len(row) > debit_col else (None, "debit")
            credit_amt, _ = (
                _parse_cc_amount(row[credit_col])
                if credit_col and len(row) > credit_col
                else (None, "credit")
            )
            if debit_amt:
                amount, direction = debit_amt, "debit"
            elif credit_amt:
                amount, direction = credit_amt, "credit"
            else:
                continue
        else:
            continue

        if amount is None:
            continue

        txns.append(
            CCTxn(
                date=iso_date,
                time="",
                direction=direction,
                merchant_raw=desc,
                merchant=_clean_cc_merchant(desc) or desc,
                amount=amount,
                upi_ref="",
                bank_name=issuer,
                account_last4=last4,
                vpa="",
                remark="",
                txn_type="card",
            ).to_dict()
        )

    if not txns:
        return _parse_text_lines(text_lines, issuer, last4)

    return txns

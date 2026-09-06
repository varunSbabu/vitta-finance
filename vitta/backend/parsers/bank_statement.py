"""Indian bank statement PDF parser.

Handles account statements from major Indian banks (SBI, HDFC, ICICI,
Axis, Indian Bank, Kotak, BOB, PNB, etc.). These PDFs are typically
table-based with columns:

    Date | Narration/Description | Ref/Chq No | Debit | Credit | Balance

The narration field is the richest data source in the Indian banking
ecosystem — it contains UPI VPAs, payee names, payment remarks, IFSC
codes, and UPI transaction IDs that no UPI app export provides.

UPI narration formats (vary by bank, all handled):
  UPI/618250019059/NAGARAJC/nagarajc@axl/coconut/IndianBank/IDIB000K005
  UPI-618250019059-NAGARAJC-nagarajc@axl-coconut
  UPI/CR/618250019059/ROHITHTAMBE/rohith@ybl/payment
  NEFT/HDFC0001234/JOHN DOE/INR 5000
  IMPS/123456789012/MERCHANT/9876543210
  ATM-NFS/CASH WDL/ATM ID 1234
  BIL/BPAY/000123456/BESCOM
  INT/INTEREST CREDIT

Also handles password-protected PDFs (banks commonly use DDMMYYYYformat
DOB-based passwords).
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
class BankTxn:
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
    source: str = "bank_pdf"

    def to_dict(self):
        return asdict(self)


# ── Date formats seen across Indian banks ──────────────────────────
DATE_FORMATS = [
    "%d/%m/%Y",  # 01/07/2026 — most common
    "%d-%m-%Y",  # 01-07-2026
    "%d %b %Y",  # 01 Jul 2026
    "%d/%m/%y",  # 01/07/26
    "%d-%m-%y",  # 01-07-26
    "%d %b %y",  # 01 Jul 26
    "%Y-%m-%d",  # 2026-07-01 (ISO)
    "%d %B %Y",  # 01 July 2026
]


def _parse_date(raw: str) -> Optional[str]:
    raw = raw.strip().replace("  ", " ")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── UPI narration tokenizer ─────────────────────────────────────────
# Common formats (all handled by the tokenizer below):
#   UPI/618250019059/NAGARAJC/nagarajc@axl/coconut/IndianBank/IDIB000K005
#   UPI-618250019059-NAGARAJC-nagarajc@axl-coconut
#   UPI/CR/618250019059/payee/vpa/remark/bank/ifsc
#   UPI/DR/618250019059/payee/vpa/remark
#   UPI/618250019200/ROHITH/9876543210-2@axl/dinner split
#
# The last example is why this is a hand-rolled tokenizer instead of a
# single regex with a `[/-]` character class as the delimiter: some PSPs
# append a '-N' index to a VPA to distinguish a second account linked to
# the same number (e.g. '9876543210-2@axl'). A regex that treats both
# '/' and '-' as field separators everywhere would split that VPA in half
# and lose the phone number. Real bank narrations are consistent about
# using ONE delimiter throughout, so we detect which one immediately
# follows 'UPI' and split on only that character — the VPA's internal
# '-' then survives intact whenever '/' is the real field separator.


def _tokenize_upi(text: str) -> list[str] | None:
    """Split a 'UPI...' narration into fields using only the delimiter
    that separates its top-level fields. Returns None if text doesn't
    start with UPI or has no recognizable delimiter."""
    if len(text) < 4 or text[:3].upper() != "UPI":
        return None
    delim = text[3] if text[3] in "/-" else None
    if delim is None:
        return None
    return [t for t in text.split(delim) if t != ""]


def _parse_upi_tokens(tokens: list[str]) -> dict | None:
    """tokens[0] is 'UPI'. Extracts ref/payee/vpa/remark from the rest.
    Returns None if the token shape doesn't match a recognizable UPI line
    (caller falls through to the generic fallback in that case)."""
    idx = 1
    if idx < len(tokens) and tokens[idx].upper() in ("CR", "DR"):
        idx += 1
    if idx >= len(tokens) or not tokens[idx].isdigit():
        return None
    upi_ref = tokens[idx]
    idx += 1
    if idx >= len(tokens):
        return None
    payee = tokens[idx].strip()
    idx += 1

    vpa = ""
    remark_parts: list[str] = []
    for tok in tokens[idx:]:
        tok = tok.strip()
        if not tok:
            continue
        if not vpa and "@" in tok:
            vpa = tok.lower()
            continue
        if re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", tok):
            continue  # IFSC code
        if _is_bank_name(tok):
            continue
        remark_parts.append(tok)

    return {
        "merchant_raw": payee,
        "merchant": _clean_name(payee),
        "vpa": vpa,
        "remark": " ".join(remark_parts).strip(),
        "upi_ref": upi_ref,
        "txn_type": "upi",
    }


# VPA pattern for extraction from free-text
VPA_RE = re.compile(r"([a-zA-Z0-9._-]+@[a-zA-Z]{2,})")

# NEFT: NEFT/HDFC0001234/JOHN DOE/INR 5000/remark
NEFT_PATTERN = re.compile(r"^NEFT[/-]([A-Z]{4}\d{7,11})?[/-]?(.+)", re.IGNORECASE)

# IMPS: IMPS/123456789012/MERCHANT/9876543210/remark
IMPS_PATTERN = re.compile(r"^IMPS[/-](\d{9,18})[/-](.+)", re.IGNORECASE)

# Bill payment: BIL/BPAY/000123456/BESCOM
BILL_PATTERN = re.compile(r"^BIL[/-](?:BPAY[/-])?(?:\d+[/-])?(.+)", re.IGNORECASE)

# ATM: ATM/CASH WDL or ATM-NFS/...
ATM_PATTERN = re.compile(r"^ATM", re.IGNORECASE)

# Interest credit
INTEREST_PATTERN = re.compile(r"(?:INT(?:EREST)?|INT\.?\s*CR)", re.IGNORECASE)

# EMI / loan debit
EMI_PATTERN = re.compile(r"(?:EMI|LOAN\s*(?:DEBIT|REPAY)|NACH)", re.IGNORECASE)


_BANK_NAMES = {
    "sbi",
    "state bank",
    "hdfc",
    "icici",
    "axis",
    "indian bank",
    "kotak",
    "bob",
    "bank of baroda",
    "pnb",
    "punjab national",
    "canara",
    "union bank",
    "indusind",
    "yes bank",
    "federal bank",
    "idfc",
    "bandhan",
    "boi",
    "bank of india",
    "iob",
    "indian overseas",
    "central bank",
}


def _is_bank_name(s: str) -> bool:
    """Check if a string looks like a bank name (to filter from remarks)."""
    low = s.strip().lower()
    if not low:
        return False
    if low.endswith("bank") or low.startswith("bank"):
        return True
    if low in _BANK_NAMES:
        return True
    for bn in _BANK_NAMES:
        if bn in low:
            return True
    return False


def _parse_narration(narration: str) -> dict:
    """Extract structured fields from a bank statement narration."""
    result = {
        "merchant_raw": narration.strip(),
        "merchant": "",
        "vpa": "",
        "remark": "",
        "upi_ref": "",
        "txn_type": "other",
    }

    text = narration.strip()
    if not text:
        return result

    # ── UPI (handles with-VPA and without-VPA formats, either delimiter) ──
    if text.upper().startswith("UPI"):
        tokens = _tokenize_upi(text)
        if tokens:
            parsed = _parse_upi_tokens(tokens)
            if parsed:
                result.update(parsed)
                return result

    # ── NEFT ──
    m = NEFT_PATTERN.match(text)
    if m:
        ifsc, remainder = m.groups()
        parts = re.split(r"[/-]", remainder)
        payee = parts[0].strip() if parts else remainder
        result.update(
            {
                "merchant_raw": payee,
                "merchant": _clean_name(payee),
                "txn_type": "neft",
            }
        )
        return result

    # ── IMPS ──
    m = IMPS_PATTERN.match(text)
    if m:
        ref, remainder = m.groups()
        parts = re.split(r"[/-]", remainder)
        payee = parts[0].strip() if parts else remainder
        vpa_match = VPA_RE.search(remainder)
        result.update(
            {
                "merchant_raw": payee,
                "merchant": _clean_name(payee),
                "upi_ref": ref,
                "vpa": vpa_match.group(1).lower() if vpa_match else "",
                "txn_type": "imps",
            }
        )
        return result

    # ── Bill payment ──
    m = BILL_PATTERN.match(text)
    if m:
        payee = m.group(1).strip()
        result.update(
            {
                "merchant_raw": payee,
                "merchant": _clean_name(payee),
                "txn_type": "bill",
            }
        )
        return result

    # ── ATM ──
    if ATM_PATTERN.match(text):
        result.update(
            {
                "merchant": "ATM Withdrawal",
                "txn_type": "atm",
            }
        )
        return result

    # ── Interest ──
    if INTEREST_PATTERN.search(text):
        result.update(
            {
                "merchant": "Bank Interest",
                "txn_type": "interest",
            }
        )
        return result

    # ── EMI / NACH ──
    if EMI_PATTERN.search(text):
        parts = re.split(r"[/-]", text)
        payee = text
        for p in parts:
            p = p.strip()
            if p and not re.match(r"^(?:EMI|NACH|LOAN|DEBIT|REPAY|DR|ACH)$", p, re.IGNORECASE):
                payee = p
                break
        result.update(
            {
                "merchant_raw": payee,
                "merchant": _clean_name(payee),
                "txn_type": "emi",
            }
        )
        return result

    # ── Fallback: use narration as merchant ──
    result["merchant"] = _clean_name(text)
    return result


def _clean_name(raw: str) -> str:
    """Best-effort cleanup of a payee name."""
    s = raw.strip()
    # Remove trailing numbers-only segments (account fragments)
    s = re.sub(r"\s+\d{4,}$", "", s)
    # Title-case if all upper
    if s.isupper() and len(s) > 3:
        s = s.title()
    return s


# ── Table extraction ───────────────────────────────────────────────


def _try_extract_tables(pdf) -> list[list]:
    """Try pdfplumber's table extraction across all pages."""
    all_rows = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            for row in table:
                if row:
                    all_rows.append([c.strip() if c else "" for c in row])
    return all_rows


def _try_extract_text_lines(pdf) -> list[str]:
    """Fallback: extract raw text lines."""
    lines = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for raw in text.split("\n"):
            line = raw.strip()
            if line:
                lines.append(line)
    return lines


# ── Column detection ───────────────────────────────────────────────
# Indian bank statements don't have standardized column names.
# We detect columns by matching header keywords.

DATE_HEADERS = {"date", "txn date", "transaction date", "value date", "val date", "posting date"}
NARRATION_HEADERS = {"narration", "description", "particulars", "transaction details", "remarks", "details"}
DEBIT_HEADERS = {"debit", "withdrawal", "dr", "debit amount", "withdrawal amt", "withdrawals"}
CREDIT_HEADERS = {"credit", "deposit", "cr", "credit amount", "deposit amt", "deposits"}
BALANCE_HEADERS = {"balance", "closing balance", "running balance", "bal"}
REF_HEADERS = {"ref", "chq", "cheque", "ref no", "chq no", "reference", "txn id"}


def _detect_columns(header_row: list[str]) -> dict:
    """Map column indices to semantic roles."""
    mapping = {}
    for i, cell in enumerate(header_row):
        h = cell.strip().lower().replace(".", "").replace("  ", " ")
        if h in DATE_HEADERS:
            mapping.setdefault("date", i)
        elif h in NARRATION_HEADERS:
            mapping.setdefault("narration", i)
        elif h in DEBIT_HEADERS:
            mapping.setdefault("debit", i)
        elif h in CREDIT_HEADERS:
            mapping.setdefault("credit", i)
        elif h in BALANCE_HEADERS:
            mapping.setdefault("balance", i)
        elif h in REF_HEADERS:
            mapping.setdefault("ref", i)
    return mapping


def _find_header_row(rows: list[list[str]]) -> tuple[int, dict]:
    """Scan rows for the header. Returns (index, column_mapping)."""
    for i, row in enumerate(rows):
        joined = " ".join(c.lower() for c in row if c)
        has_date = any(h in joined for h in DATE_HEADERS)
        has_narration = any(h in joined for h in NARRATION_HEADERS)
        has_amount = any(h in joined for h in DEBIT_HEADERS | CREDIT_HEADERS)
        if has_date and (has_narration or has_amount):
            mapping = _detect_columns(row)
            if "date" in mapping and ("debit" in mapping or "credit" in mapping):
                return i, mapping
    return -1, {}


def _parse_amount(raw: str) -> Optional[float]:
    """Parse an Indian-format amount: '1,23,456.78' or '₹ 1234'."""
    if not raw:
        return None
    s = raw.strip().replace("₹", "").replace("INR", "").replace(" ", "").replace(",", "")
    # Handle Dr/Cr suffixes
    s = re.sub(r"[Dd][Rr]$", "", s)
    s = re.sub(r"[Cc][Rr]$", "", s)
    s = s.strip()
    if not s:
        return None
    try:
        val = float(s)
        return val if val > 0 else None
    except ValueError:
        return None


# ── Account info extraction ────────────────────────────────────────

ACCOUNT_NUM_RE = re.compile(r"(?:A/?c|Account)\s*(?:No\.?|Number)?\s*:?\s*(\d{4,})", re.IGNORECASE)
BANK_NAME_RE = re.compile(
    r"(State Bank of India|SBI|HDFC Bank|ICICI Bank|Axis Bank|Indian Bank|"
    r"Kotak Mahindra Bank|Kotak Bank|Bank of Baroda|BOB|"
    r"Punjab National Bank|PNB|Canara Bank|Union Bank|"
    r"IndusInd Bank|Yes Bank|Federal Bank|"
    r"IDFC First Bank|IDFC Bank|Bandhan Bank|"
    r"Bank of India|BOI|Central Bank|"
    r"Indian Overseas Bank|IOB)",
    re.IGNORECASE,
)


# First 4 letters of the account's own IFSC (e.g. "IFSC IDIB000A682")
# reliably identify the bank even when the statement never spells the
# bank's name out in its first few pages — some exports only print it in
# a page footer, which can land past whatever page window gets scanned.
IFSC_PREFIX_TO_BANK = {
    "SBIN": "State Bank of India",
    "HDFC": "HDFC Bank",
    "ICIC": "ICICI Bank",
    "UTIB": "Axis Bank",
    "IDIB": "Indian Bank",
    "KKBK": "Kotak Mahindra Bank",
    "BARB": "Bank of Baroda",
    "PUNB": "Punjab National Bank",
    "CNRB": "Canara Bank",
    "UBIN": "Union Bank of India",
    "IBKL": "IDBI Bank",
    "INDB": "IndusInd Bank",
    "YESB": "Yes Bank",
    "FDRL": "Federal Bank",
    "IDFB": "IDFC First Bank",
    "BDBL": "Bandhan Bank",
    "BKID": "Bank of India",
    "CBIN": "Central Bank of India",
    "IOBA": "Indian Overseas Bank",
}
STATEMENT_IFSC_RE = re.compile(r"\bIFSC\b\s*:?\s*([A-Z]{4})[A-Z0-9]{7}\b", re.IGNORECASE)


def _extract_account_info(text_lines: list[str]) -> tuple[str, str]:
    """Extract bank name and last4 of account from header area."""
    bank_name = ""
    account_last4 = ""
    for line in text_lines[:30]:
        if not bank_name:
            m = BANK_NAME_RE.search(line)
            if m:
                bank_name = m.group(1).strip()
        if not account_last4:
            m = ACCOUNT_NUM_RE.search(line)
            if m:
                num = m.group(1)
                account_last4 = num[-4:]
        if bank_name and account_last4:
            break

    if not bank_name:
        for line in text_lines[:30]:
            m = STATEMENT_IFSC_RE.search(line)
            if m:
                bank_name = IFSC_PREFIX_TO_BANK.get(m.group(1).upper(), "")
                if bank_name:
                    break

    return bank_name, account_last4


# ── Main parse function ───────────────────────────────────────────


def parse(path: str, password: str | None = None) -> list[dict]:
    """Parse an Indian bank statement PDF.

    Args:
        path: Path to the PDF file.
        password: Optional password (banks often use DDMMYYYY DOB).

    Returns:
        List of transaction dicts ready for import.
    """
    open_kwargs = {}
    if password:
        open_kwargs["password"] = password

    with pdfplumber.open(path, **open_kwargs) as pdf:
        # Extract text for account info
        text_lines = []
        for page in pdf.pages[:3]:
            text = page.extract_text() or ""
            text_lines.extend(text.split("\n"))

        bank_name, account_last4 = _extract_account_info(text_lines)

        # Try table extraction first
        rows = _try_extract_tables(pdf)

    if not rows:
        return _parse_text_fallback(path, password, bank_name, account_last4)

    header_idx, col_map = _find_header_row(rows)
    if header_idx < 0:
        return _parse_text_fallback(path, password, bank_name, account_last4)

    txns = []
    date_col = col_map["date"]
    narration_col = col_map.get("narration")
    debit_col = col_map.get("debit")
    credit_col = col_map.get("credit")

    for row in rows[header_idx + 1 :]:
        if len(row) <= date_col:
            continue

        iso_date = _parse_date(row[date_col])
        if not iso_date:
            continue

        narration = (
            row[narration_col].strip() if narration_col is not None and len(row) > narration_col else ""
        )
        if not narration:
            continue

        debit_amt = _parse_amount(row[debit_col]) if debit_col is not None and len(row) > debit_col else None
        credit_amt = (
            _parse_amount(row[credit_col]) if credit_col is not None and len(row) > credit_col else None
        )

        if debit_amt is None and credit_amt is None:
            continue

        direction = "debit" if debit_amt else "credit"
        amount = debit_amt or credit_amt

        parsed = _parse_narration(narration)

        txns.append(
            BankTxn(
                date=iso_date,
                time="",
                direction=direction,
                merchant_raw=parsed["merchant_raw"],
                merchant=parsed["merchant"] or parsed["merchant_raw"],
                amount=amount,
                upi_ref=parsed["upi_ref"],
                bank_name=bank_name,
                account_last4=account_last4,
                vpa=parsed["vpa"],
                remark=parsed["remark"],
                txn_type=parsed["txn_type"],
            ).to_dict()
        )

    return txns


# ── Multi-line wrapped format ────────────────────────────────────────
# Some banks (Indian Bank's own "IndOASIS" net-banking export among them)
# render the transaction table as plain positioned text with no vector
# gridlines at all, so pdfplumber's extract_tables() finds nothing on
# these pages. Worse: each transaction's narration wraps across several
# physical lines, sometimes splitting mid-word ('coconu' + 't' ->
# 'coconut', 'balanc' + 'e' -> 'balance'), and the UPI ref+remark sit at
# the END of the narration instead of the start — the reverse of the
# UPI/ref/payee/vpa/remark shape the tokenizer above handles. Real sample:
#
#   04 Aug 2026 HDFC0004699/P INR 10,000.00 - INR 19,137.51
#   SHREYAS GOWDA
#   /XXXXX43681/6361943681-
#   3@axl
#   /UPI/621641459779/mane
#
# — one logical transaction split across 5 lines. Concatenating the
# continuation lines with NO separator (since the wraps are mid-token,
# not at word boundaries) reconstructs:
#   'HDFC0004699/PSHREYAS GOWDA/XXXXX43681/6361943681-3@axl/UPI/621641459779/mane'

WRAPPED_DATE_LINE_RE = re.compile(r"^(\d{2}) ([A-Za-z]{3}) (\d{4})\s+(.*)$")
_WRAPPED_AMOUNT_TOKEN = r"(?:INR\s*[\d,]+\.\d{2}|-)"
WRAPPED_TRAILING_AMOUNTS_RE = re.compile(
    rf"({_WRAPPED_AMOUNT_TOKEN})\s+({_WRAPPED_AMOUNT_TOKEN})\s+({_WRAPPED_AMOUNT_TOKEN})\s*$"
)
WRAPPED_TRAILING_UPI_RE = re.compile(r"/UPI/(\d{6,18})/(.*)$", re.IGNORECASE)
WRAPPED_TABLE_HEADER_RE = re.compile(
    r"^Date\s+Transaction Details\s+Debits\s+Credits\s+Balance$", re.IGNORECASE
)
WRAPPED_END_MARKERS = ("Ending Balance", "Total ", "Total INR")
WRAPPED_MASKED_ACCOUNT_RE = re.compile(r"/?X{3,}\d*")
WRAPPED_IFSC_PREFIX_RE = re.compile(r"^([A-Z]{4}0[A-Z0-9]{6})/?")


def _looks_like_wrapped_statement(lines: list[str]) -> bool:
    """True if this text has the date-then-trailing-amounts shape this
    format uses, so the caller knows to try this parser before the more
    generic (and, for this shape, ineffective) LINE_PATTERN fallback."""
    for line in lines:
        m = WRAPPED_DATE_LINE_RE.match(line.strip())
        if m and WRAPPED_TRAILING_AMOUNTS_RE.search(m.group(4)):
            return True
    return False


def _parse_wrapped_inr(token: str) -> Optional[float]:
    token = token.strip()
    if token == "-" or not token:
        return None
    token = token.replace("INR", "").replace(",", "").strip()
    try:
        v = float(token)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_wrapped_narration(narration: str) -> dict:
    """Extract payee/VPA/UPI-ref/remark from a reconstructed (concatenated)
    narration where the UPI block trails at the end rather than leading."""
    result = {
        "merchant_raw": narration,
        "merchant": "",
        "vpa": "",
        "remark": "",
        "upi_ref": "",
        "txn_type": "other",
    }

    upi_m = WRAPPED_TRAILING_UPI_RE.search(narration)
    head = narration[: upi_m.start()] if upi_m else narration

    vpa = ""
    vpa_m = VPA_RE.search(head)
    head_before_vpa = head
    if vpa_m:
        vpa = vpa_m.group(1).lower()
        head_before_vpa = head[: vpa_m.start()]

    payee = head_before_vpa
    ifsc_m = WRAPPED_IFSC_PREFIX_RE.match(payee)
    if ifsc_m:
        payee = payee[ifsc_m.end() :]
    masked_m = WRAPPED_MASKED_ACCOUNT_RE.search(payee)
    if masked_m:
        payee = payee[: masked_m.start()]
    payee = payee.strip("/ ").strip()
    if not payee:
        payee = narration[:40].strip("/ ").strip()  # last resort — some slice beats nothing

    if upi_m:
        result.update(
            {
                "upi_ref": upi_m.group(1),
                "remark": upi_m.group(2).strip("/ ").strip(),
                "vpa": vpa,
                "txn_type": "upi",
            }
        )
    elif vpa:
        result.update({"vpa": vpa, "txn_type": "upi"})

    result["merchant_raw"] = payee
    result["merchant"] = _clean_name(payee)
    return result


def _parse_wrapped_multiline(lines: list[str], bank_name: str, account_last4: str) -> list[dict]:
    txns = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].strip()
        m = WRAPPED_DATE_LINE_RE.match(line)
        if not m:
            i += 1
            continue

        dd, mon, yyyy, rest = m.groups()
        iso_date = _parse_date(f"{dd} {mon} {yyyy}")
        if not iso_date:
            i += 1
            continue

        amt_m = WRAPPED_TRAILING_AMOUNTS_RE.search(rest)
        if not amt_m:
            i += 1
            continue

        prefix = rest[: amt_m.start()].strip()
        debit_tok, credit_tok, _balance_tok = amt_m.groups()
        debit = _parse_wrapped_inr(debit_tok)
        credit = _parse_wrapped_inr(credit_tok)
        if debit is None and credit is None:
            i += 1
            continue
        direction = "debit" if debit is not None else "credit"
        amount = debit if debit is not None else credit

        # Continuation lines: everything until the next date-line, a
        # repeated per-page table header, or an end-of-statement marker.
        j = i + 1
        cont_parts = []
        while j < n:
            nxt = lines[j].strip()
            if not nxt:
                j += 1
                continue
            if (
                WRAPPED_DATE_LINE_RE.match(nxt)
                or WRAPPED_TABLE_HEADER_RE.match(nxt)
                or nxt.startswith(WRAPPED_END_MARKERS)
            ):
                break
            cont_parts.append(nxt)
            j += 1

        narration = prefix + "".join(cont_parts)
        parsed = _parse_wrapped_narration(narration)

        txns.append(
            BankTxn(
                date=iso_date,
                time="",
                direction=direction,
                merchant_raw=parsed["merchant_raw"],
                merchant=parsed["merchant"] or parsed["merchant_raw"],
                amount=amount,
                upi_ref=parsed["upi_ref"],
                bank_name=bank_name,
                account_last4=account_last4,
                vpa=parsed["vpa"],
                remark=parsed["remark"],
                txn_type=parsed["txn_type"],
            ).to_dict()
        )

        i = j

    return txns


# ── Text-line fallback ─────────────────────────────────────────────
# For PDFs where table extraction fails (scanned or oddly formatted).
# Tries to find date + amount patterns in each line.

LINE_PATTERN = re.compile(
    r"(\d{2}[/-]\d{2}[/-]\d{2,4})"  # date
    r"\s+(.+?)"  # narration (greedy middle)
    r"\s+([\d,]+\.\d{2})\s*"  # first amount
    r"(?:([\d,]+\.\d{2})\s*)?"  # optional second amount
    r"(?:([\d,]+\.\d{2}))?"  # optional balance
)


def _parse_text_fallback(path: str, password: str | None, bank_name: str, account_last4: str) -> list[dict]:
    open_kwargs = {}
    if password:
        open_kwargs["password"] = password

    all_lines = []
    with pdfplumber.open(path, **open_kwargs) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.extend(text.split("\n"))

    if _looks_like_wrapped_statement(all_lines):
        wrapped = _parse_wrapped_multiline(all_lines, bank_name, account_last4)
        if wrapped:
            return wrapped

    txns = []
    for line in all_lines:
        line = line.strip()
        m = LINE_PATTERN.match(line)
        if not m:
            continue

        date_raw, narration, amt1, amt2, _bal = m.groups()
        iso_date = _parse_date(date_raw)
        if not iso_date:
            continue

        narration = narration.strip()
        if not narration:
            continue

        # Heuristic: if two amounts present, first=debit second=credit (or vice versa)
        if amt1 and amt2:
            d = _parse_amount(amt1)
            c = _parse_amount(amt2)
            if d and not c:
                direction, amount = "debit", d
            elif c and not d:
                direction, amount = "credit", c
            else:
                direction, amount = "debit", d
        elif amt1:
            amount = _parse_amount(amt1)
            if not amount:
                continue
            direction = "debit"
        else:
            continue

        parsed = _parse_narration(narration)

        txns.append(
            BankTxn(
                date=iso_date,
                time="",
                direction=direction,
                merchant_raw=parsed["merchant_raw"],
                merchant=parsed["merchant"] or parsed["merchant_raw"],
                amount=amount,
                upi_ref=parsed["upi_ref"],
                bank_name=bank_name,
                account_last4=account_last4,
                vpa=parsed["vpa"],
                remark=parsed["remark"],
                txn_type=parsed["txn_type"],
            ).to_dict()
        )

    return txns


if __name__ == "__main__":
    import json
    import sys

    args = sys.argv[1:]
    if not args:
        print("usage: python -m parsers.bank_statement <path.pdf> [password]", file=sys.stderr)
        sys.exit(1)

    pdf_path = args[0]
    pwd = args[1] if len(args) > 1 else None
    result = parse(pdf_path, pwd)

    print(f"# {len(result)} transactions parsed", file=sys.stderr)
    debits = [t for t in result if t["direction"] == "debit"]
    credits = [t for t in result if t["direction"] == "credit"]
    print(f"# debits: {len(debits)} totaling ₹{sum(t['amount'] for t in debits):,.2f}", file=sys.stderr)
    print(f"# credits: {len(credits)} totaling ₹{sum(t['amount'] for t in credits):,.2f}", file=sys.stderr)

    upi = [t for t in result if t["txn_type"] == "upi"]
    with_remark = [t for t in upi if t["remark"]]
    with_vpa = [t for t in upi if t["vpa"]]
    print(f"# UPI: {len(upi)} ({len(with_vpa)} with VPA, {len(with_remark)} with remark)", file=sys.stderr)

    print(json.dumps(result, indent=2, ensure_ascii=False))

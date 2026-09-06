"""Google Contacts CSV import + VPA phone matching.

Google's "Export contacts" CSV has dozens of columns; the ones we care
about are the display name and any "Phone N - Value" columns. We
normalize phone numbers to their last 10 digits (Indian mobile numbers)
and store them so incoming UPI VPAs like '9876543210@ybl' or
'9876543210-2@axl' resolve to a real name instead of a raw bank-registered
name blob like 'SANTHOSHKUMARREDDY'.
"""

from __future__ import annotations

import csv
import io
import re

from db import get_conn

DIGITS_RE = re.compile(r"\d+")


def _normalize_phone(raw: str) -> str | None:
    """Extract the last 10 digits from a phone string, or None if too short.
    Handles '+91 98765 43210', '098765-43210', '9876543210', etc. — the
    digit groups here are all pieces of the SAME number, so concatenating
    every run is correct."""
    digits = "".join(DIGITS_RE.findall(raw))
    if len(digits) < 10:
        return None
    return digits[-10:]


def _extract_vpa_phone(local_part: str) -> str | None:
    """Extract a phone number from a VPA local part, e.g. '9876543210' in
    '9876543210@ybl' or '9876543210-2@axl'. Unlike _normalize_phone, this
    must NOT blindly concatenate every digit run — some PSPs append a
    small '-N' index to distinguish a second account on the same number
    (e.g. '9876543210-2'), and joining that '2' onto the end would shift
    the last-10-digit window and corrupt the match. Prefer a single
    standalone run of >=10 digits; only fall back to concatenation for
    numbers split across separators (e.g. '98765 43210')."""
    for run in DIGITS_RE.findall(local_part):
        if len(run) >= 10:
            return run[-10:]
    digits = "".join(DIGITS_RE.findall(local_part))
    if len(digits) >= 10:
        return digits[-10:]
    return None


def parse_google_contacts_csv(content: bytes) -> list[dict]:
    """Parse a Google Contacts export CSV into [{phone_last10, display_name}, ...].
    Deduplicates by phone number (first name seen wins)."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    contacts: list[dict] = []
    seen_phones: set[str] = set()

    for row in reader:
        name = (row.get("Name") or "").strip()
        if not name:
            given = (row.get("Given Name") or "").strip()
            family = (row.get("Family Name") or "").strip()
            name = f"{given} {family}".strip()
        if not name:
            continue

        phones: set[str] = set()
        for key, value in row.items():
            if not value or not key:
                continue
            if "Phone" in key and "Value" in key:
                norm = _normalize_phone(value)
                if norm:
                    phones.add(norm)

        for phone in phones:
            if phone in seen_phones:
                continue
            seen_phones.add(phone)
            contacts.append({"phone_last10": phone, "display_name": name})

    return contacts


def import_contacts(parsed: list[dict]) -> dict:
    """Upsert parsed contacts into the DB."""
    conn = get_conn()
    for c in parsed:
        conn.execute(
            """
            INSERT INTO contacts (phone_last10, display_name)
            VALUES (?, ?)
            ON CONFLICT(phone_last10) DO UPDATE SET display_name = excluded.display_name
            """,
            (c["phone_last10"], c["display_name"]),
        )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) AS c FROM contacts").fetchone()["c"]
    conn.close()
    return {"rows_in_csv": len(parsed), "total_contacts": total}


def resolve_vpa_to_name(vpa: str) -> str | None:
    """Given a VPA like '9876543210@ybl' or '9876543210-2@axl', look up a
    matching contact by the phone number embedded in the VPA's local part."""
    if not vpa or "@" not in vpa:
        return None
    local_part = vpa.split("@", 1)[0]
    last10 = _extract_vpa_phone(local_part)
    if not last10:
        return None

    conn = get_conn()
    row = conn.execute(
        "SELECT display_name FROM contacts WHERE phone_last10 = ?",
        (last10,),
    ).fetchone()
    conn.close()
    return row["display_name"] if row else None


def resolve_contacts_batch(vpas: list[str]) -> dict[str, str]:
    """Resolve many VPAs in one DB round-trip. Returns {vpa: display_name}
    for only the ones that matched."""
    last10_by_vpa: dict[str, str] = {}
    for vpa in vpas:
        if not vpa or "@" not in vpa:
            continue
        local_part = vpa.split("@", 1)[0]
        last10 = _extract_vpa_phone(local_part)
        if last10:
            last10_by_vpa[vpa] = last10

    if not last10_by_vpa:
        return {}

    unique_last10 = list(set(last10_by_vpa.values()))
    placeholders = ",".join("?" * len(unique_last10))
    conn = get_conn()
    rows = conn.execute(
        f"SELECT phone_last10, display_name FROM contacts WHERE phone_last10 IN ({placeholders})",
        unique_last10,
    ).fetchall()
    conn.close()

    name_by_phone = {r["phone_last10"]: r["display_name"] for r in rows}
    return {vpa: name_by_phone[last10] for vpa, last10 in last10_by_vpa.items() if last10 in name_by_phone}

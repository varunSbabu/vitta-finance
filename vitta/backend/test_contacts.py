"""Tests for Google Contacts CSV parsing + VPA phone matching."""

# ruff: noqa: E402 — db.DB_PATH must be pointed at a scratch file before
# `import db` triggers anything that opens a connection.
import os
import pathlib
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()

import db

db.DB_PATH = pathlib.Path(_tmp_db.name)
db.init_db()

from contacts import (  # noqa: E402
    _normalize_phone,
    import_contacts,
    parse_google_contacts_csv,
    resolve_contacts_batch,
    resolve_vpa_to_name,
)

TEST_USER_ID = 1


@pytest.fixture(autouse=True)
def _scratch_db():
    db.DB_PATH = pathlib.Path(_tmp_db.name)
    db.init_db()
    _ensure_test_user()
    yield


def _ensure_test_user():
    conn = db.get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, name) VALUES (?, 'test@example.com', 'Test')",
        (TEST_USER_ID,),
    )
    conn.commit()
    conn.close()


def _reset():
    conn = db.get_conn()
    conn.execute("DELETE FROM contacts")
    conn.commit()
    conn.close()


def test_normalize_phone_formats():
    assert _normalize_phone("+91 98765 43210") == "9876543210"
    assert _normalize_phone("098765-43210") == "9876543210"
    assert _normalize_phone("9876543210") == "9876543210"
    assert _normalize_phone("919876543210") == "9876543210"
    assert _normalize_phone("12345") is None
    assert _normalize_phone("") is None
    print("  OK phone normalization across formats")


def test_csv_parsing_name_column():
    csv_bytes = b"Name,Given Name,Family Name,Phone 1 - Value\nRohith Tambe,Rohith,Tambe,+91 98765 43210\n"
    rows = parse_google_contacts_csv(csv_bytes)
    assert len(rows) == 1
    assert rows[0] == {"phone_last10": "9876543210", "display_name": "Rohith Tambe"}
    print("  OK CSV parsing with Name column")


def test_csv_parsing_given_family_fallback():
    csv_bytes = b"Given Name,Family Name,Phone 1 - Value\nNagaraj,C,9123456789\n"
    rows = parse_google_contacts_csv(csv_bytes)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Nagaraj C"
    assert rows[0]["phone_last10"] == "9123456789"
    print("  OK CSV parsing falls back to Given+Family Name")


def test_csv_parsing_multiple_phones_dedup():
    csv_bytes = b"Name,Phone 1 - Value,Phone 2 - Value\nAmma,9876500000,9876500000\n"
    rows = parse_google_contacts_csv(csv_bytes)
    assert len(rows) == 1
    print("  OK duplicate phone across columns collapses to one row")


def test_csv_parsing_skips_no_phone():
    csv_bytes = b"Name,Phone 1 - Value\nNo Phone Guy,\n"
    rows = parse_google_contacts_csv(csv_bytes)
    assert len(rows) == 0
    print("  OK contact with no phone is skipped")


def test_import_and_resolve_vpa():
    _reset()
    import_contacts([{"phone_last10": "9876543210", "display_name": "Rohith Tambe"}], TEST_USER_ID)

    assert resolve_vpa_to_name("9876543210@ybl", TEST_USER_ID) == "Rohith Tambe"
    assert resolve_vpa_to_name("9876543210-2@axl", TEST_USER_ID) == "Rohith Tambe"
    assert resolve_vpa_to_name("919876543210@paytm", TEST_USER_ID) == "Rohith Tambe"
    print("  OK VPA resolution across VPA suffix variants")


def test_resolve_vpa_no_match():
    _reset()
    import_contacts([{"phone_last10": "9876543210", "display_name": "Rohith Tambe"}], TEST_USER_ID)
    assert resolve_vpa_to_name("9999999999@ybl", TEST_USER_ID) is None
    assert resolve_vpa_to_name("rohith@ybl", TEST_USER_ID) is None
    assert resolve_vpa_to_name("", TEST_USER_ID) is None
    print("  OK non-matching / alias / empty VPAs return None")


def test_import_upsert_updates_name():
    _reset()
    import_contacts([{"phone_last10": "9876543210", "display_name": "Old Name"}], TEST_USER_ID)
    import_contacts([{"phone_last10": "9876543210", "display_name": "New Name"}], TEST_USER_ID)
    assert resolve_vpa_to_name("9876543210@ybl", TEST_USER_ID) == "New Name"
    print("  OK re-importing same phone updates the display name")


def test_resolve_batch():
    _reset()
    import_contacts(
        [
            {"phone_last10": "9876543210", "display_name": "Rohith Tambe"},
            {"phone_last10": "9123456789", "display_name": "Nagaraj C"},
        ],
        TEST_USER_ID,
    )
    result = resolve_contacts_batch(
        ["9876543210@ybl", "9123456789@axl", "unknown@ybl", "8888888888@ybl"], TEST_USER_ID
    )
    assert result == {"9876543210@ybl": "Rohith Tambe", "9123456789@axl": "Nagaraj C"}
    print("  OK batch resolve returns only matched VPAs")


def test_resolve_batch_empty():
    _reset()
    assert resolve_contacts_batch([], TEST_USER_ID) == {}
    assert resolve_contacts_batch(["noatsign", None], TEST_USER_ID) == {}
    print("  OK batch resolve handles empty/garbage input")


if __name__ == "__main__":
    tests = [
        test_normalize_phone_formats,
        test_csv_parsing_name_column,
        test_csv_parsing_given_family_fallback,
        test_csv_parsing_multiple_phones_dedup,
        test_csv_parsing_skips_no_phone,
        test_import_and_resolve_vpa,
        test_resolve_vpa_no_match,
        test_import_upsert_updates_name,
        test_resolve_batch,
        test_resolve_batch_empty,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    os.unlink(_tmp_db.name)

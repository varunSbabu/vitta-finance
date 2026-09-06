"""Tests for bank statement narration parser."""

from parsers.bank_statement import (
    _extract_account_info,
    _looks_like_wrapped_statement,
    _parse_amount,
    _parse_date,
    _parse_narration,
    _parse_wrapped_multiline,
    _parse_wrapped_narration,
)

# Synthetic lines reproducing the shape of Indian Bank's real "IndOASIS"
# export (no vector table gridlines, so pdfplumber finds no tables; each
# transaction's narration wraps across several lines, sometimes splitting
# mid-word, with the UPI ref+remark trailing at the END of the narration
# instead of leading it). Values here are fabricated, not real account data.
WRAPPED_SAMPLE_LINES = [
    "ACCOUNT STATEMENT",
    "Last 30 Transactions",
    "ACCOUNT DETAILS ACCOUNT SUMMARY",
    "Account Holder Name TEST USER",
    "Account Number 1234567890 Total Credits + INR 1,000.00",
    "IFSC IDIB000A682",
    "ACCOUNT ACTIVITY",
    "Date Transaction Details Debits Credits Balance",
    "04 Aug 2026 HDFC0004699/P INR 10,000.00 - INR 19,137.51",
    "SOME PAYEE",
    "/XXXXX43681/6361943681-",
    "3@axl",
    "/UPI/621641459779/mane",
    "05 Aug 2026 YESB0PTMUPI/SANTHOS INR 30.00 - INR 15,532.51",
    "HKUMAR GANESAN",
    "/XXXXX",
    "/paytmqr6vwkjv@ptys",
    "/UPI/621744987995/coconu",
    "t",
    "13 Aug 2026 YESB0000022/PhonePe - INR 15,000.00 INR 15,667.51",
    "/XXXXX33311/ppewalletwit",
    "hdrawl@yesbank",
    "/UPI/622511157625/F02",
    "PhonePe WD T2608",
    "17 Aug 2026 ATM_AMC_Charges000000 INR 93.51 - INR 0.00",
    "00000098014",
    "Ending Balance INR 0.00",
    "Total INR 89,757.51 INR 60,620.00",
    "Indian Bank | | 5/5",
]


def test_upi_full():
    r = _parse_narration("UPI/618250019059/NAGARAJC/nagarajc@axl/coconut/IndianBank/IDIB000K005")
    assert r["txn_type"] == "upi"
    assert r["upi_ref"] == "618250019059"
    assert r["vpa"] == "nagarajc@axl"
    assert r["merchant_raw"] == "NAGARAJC"
    assert "coconut" in r["remark"].lower()
    print(f"  OK full UPI: merchant={r['merchant']}, vpa={r['vpa']}, remark={r['remark']}")


def test_upi_cr():
    r = _parse_narration("UPI/CR/618250019059/ROHITHTAMBE/rohith@ybl/payment for lunch")
    assert r["txn_type"] == "upi"
    assert r["upi_ref"] == "618250019059"
    assert r["vpa"] == "rohith@ybl"
    assert r["merchant_raw"] == "ROHITHTAMBE"
    print(f"  OK UPI CR: merchant={r['merchant']}, remark={r['remark']}")


def test_upi_dash():
    r = _parse_narration("UPI-618250019059-SWIGGY-swiggy@axisbank-order 123")
    assert r["txn_type"] == "upi"
    assert r["upi_ref"] == "618250019059"
    assert r["vpa"] == "swiggy@axisbank"
    print(f"  OK UPI dash: merchant={r['merchant']}, vpa={r['vpa']}")


def test_upi_vpa_with_dash_suffix():
    # Some PSPs append '-N' to a VPA for a second account on the same
    # number. With '/' as the real delimiter, that dash must NOT be
    # treated as a field separator or the VPA gets truncated.
    r = _parse_narration("UPI/618250019200/ROHITH/9876543210-2@axl/dinner split")
    assert r["txn_type"] == "upi"
    assert r["vpa"] == "9876543210-2@axl"
    assert r["upi_ref"] == "618250019200"
    assert r["merchant_raw"] == "ROHITH"
    print(f"  OK VPA with dash suffix stays intact: vpa={r['vpa']}")


def test_upi_short():
    r = _parse_narration("UPI/618250019059/RAPIDO BIKE TAXI")
    assert r["txn_type"] == "upi"
    assert r["upi_ref"] == "618250019059"
    assert "RAPIDO" in r["merchant_raw"]
    print(f"  OK UPI short: merchant={r['merchant']}")


def test_neft():
    r = _parse_narration("NEFT/HDFC0001234/JOHN DOE/INR 5000/salary")
    assert r["txn_type"] == "neft"
    assert r["merchant"] == "John Doe"
    print(f"  OK NEFT: merchant={r['merchant']}")


def test_imps():
    r = _parse_narration("IMPS/123456789012/MERCHANT NAME/9876543210")
    assert r["txn_type"] == "imps"
    assert r["upi_ref"] == "123456789012"
    print(f"  OK IMPS: merchant={r['merchant']}")


def test_atm():
    r = _parse_narration("ATM-NFS/CASH WDL/ATM ID 1234")
    assert r["txn_type"] == "atm"
    assert r["merchant"] == "ATM Withdrawal"
    print(f"  OK ATM: merchant={r['merchant']}")


def test_bill():
    r = _parse_narration("BIL/BPAY/000123456/BESCOM ELECTRICITY")
    assert r["txn_type"] == "bill"
    print(f"  OK BILL: merchant={r['merchant']}")


def test_interest():
    r = _parse_narration("INT/INTEREST CREDIT/Q4 2026")
    assert r["txn_type"] == "interest"
    print(f"  OK INTEREST: merchant={r['merchant']}")


def test_emi():
    r = _parse_narration("NACH/HDFC HOME LOAN/EMI DEBIT")
    assert r["txn_type"] == "emi"
    print(f"  OK EMI: merchant={r['merchant']}")


def test_dates():
    assert _parse_date("01/07/2026") == "2026-07-01"
    assert _parse_date("01-07-2026") == "2026-07-01"
    assert _parse_date("01 Jul 2026") == "2026-07-01"
    assert _parse_date("01/07/26") == "2026-07-01"
    assert _parse_date("2026-07-01") == "2026-07-01"
    print("  OK all date formats")


def test_amounts():
    assert _parse_amount("1,23,456.78") == 123456.78
    assert _parse_amount("₹ 1234.00") == 1234.0
    assert _parse_amount("5000.00Dr") == 5000.0
    assert _parse_amount("2,500.50 Cr") == 2500.5
    assert _parse_amount("") is None
    assert _parse_amount("   ") is None
    print("  OK all amount formats")


def test_wrapped_statement_detection():
    assert _looks_like_wrapped_statement(WRAPPED_SAMPLE_LINES) is True
    assert _looks_like_wrapped_statement(["random text", "no dates here"]) is False
    print("  OK wrapped-format detector fires only on the real shape")


def test_wrapped_narration_upi_trailing():
    # UPI ref+remark trail at the END here, opposite of the leading-UPI
    # format the main tokenizer handles — this is why a separate parser
    # exists for this bank's export.
    narration = "HDFC0004699/PSOME PAYEE/XXXXX43681/6361943681-3@axl/UPI/621641459779/mane"
    r = _parse_wrapped_narration(narration)
    assert r["txn_type"] == "upi"
    assert r["upi_ref"] == "621641459779"
    assert r["remark"] == "mane"
    assert r["vpa"] == "6361943681-3@axl"
    print(f"  OK trailing-UPI narration: merchant={r['merchant']!r}, vpa={r['vpa']}, remark={r['remark']}")


def test_wrapped_narration_no_upi_marker():
    # Bank fee lines (ATM AMC charges etc.) have no UPI block at all.
    r = _parse_wrapped_narration("ATM_AMC_Charges00000000000098014")
    assert r["txn_type"] == "other"
    assert r["upi_ref"] == ""
    assert r["vpa"] == ""
    print(f"  OK non-UPI (fee) narration doesn't fabricate a UPI ref: merchant={r['merchant']!r}")


def test_wrapped_multiline_full_parse():
    txns = _parse_wrapped_multiline(WRAPPED_SAMPLE_LINES, "Indian Bank", "7318")
    assert len(txns) == 4  # 3 UPI txns + 1 ATM fee line; header/footer/total lines excluded
    dates = [t["date"] for t in txns]
    assert dates == ["2026-08-04", "2026-08-05", "2026-08-13", "2026-08-17"]

    t0 = txns[0]
    assert t0["direction"] == "debit"
    assert t0["amount"] == 10000.0
    assert t0["upi_ref"] == "621641459779"
    assert t0["remark"] == "mane"

    t1 = txns[1]
    assert t1["remark"] == "coconut"  # 'coconu' + 't' across the line wrap must rejoin correctly
    assert t1["vpa"] == "paytmqr6vwkjv@ptys"

    t2 = txns[2]
    assert t2["direction"] == "credit"  # debit column is '-', credit column has the amount
    assert t2["amount"] == 15000.0

    t3 = txns[3]
    assert t3["direction"] == "debit"
    assert t3["amount"] == 93.51
    assert t3["upi_ref"] == ""  # fee line — no UPI block to find

    for t in txns:
        assert t["bank_name"] == "Indian Bank"
        assert t["account_last4"] == "7318"

    print(f"  OK full wrapped-multiline parse: {len(txns)}/4 transactions, all fields correct")


def test_wrapped_multiline_skips_repeated_page_header():
    # A per-page-repeated "Date Transaction Details..." header row must
    # never get swallowed into the previous transaction's continuation
    # lines, or it would corrupt that transaction's remark.
    lines = (
        WRAPPED_SAMPLE_LINES[:13]
        + ["Date Transaction Details Debits Credits Balance"]
        + WRAPPED_SAMPLE_LINES[13:]
    )
    txns = _parse_wrapped_multiline(lines, "Indian Bank", "7318")
    assert len(txns) == 4
    assert txns[0]["remark"] == "mane"  # unaffected by the header row inserted right after it
    print("  OK repeated page-header row doesn't corrupt the preceding transaction")


def test_ifsc_prefix_bank_inference():
    # Some exports never spell the bank's name out on the pages scanned
    # for header info — only the account's own IFSC gives it away.
    lines = ["Account Number 7554027318", "IFSC IDIB000A682"]
    bank, last4 = _extract_account_info(lines)
    assert bank == "Indian Bank"
    assert last4 == "7318"
    print(f"  OK bank name inferred from IFSC prefix when no bank name text is present: {bank}")


if __name__ == "__main__":
    tests = [
        test_upi_full,
        test_upi_cr,
        test_upi_dash,
        test_upi_vpa_with_dash_suffix,
        test_upi_short,
        test_neft,
        test_imps,
        test_atm,
        test_bill,
        test_interest,
        test_emi,
        test_dates,
        test_amounts,
        test_wrapped_statement_detection,
        test_wrapped_narration_upi_trailing,
        test_wrapped_narration_no_upi_marker,
        test_wrapped_multiline_full_parse,
        test_wrapped_multiline_skips_repeated_page_header,
        test_ifsc_prefix_bank_inference,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")

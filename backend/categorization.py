"""Tier 1 categorization — deterministic rules on merchant name.

Order of resolution:
1. User dictionary lookup (exact merchant_key match) — Tier 2, in main.py
2. Rules below — Tier 1
3. Fall through to 'Uncategorized'
"""
from __future__ import annotations

# Substrings tested case-insensitively against the raw merchant string.
# First match wins.
MERCHANT_RULES: list[tuple[str, str]] = [
    # Groceries / quick commerce
    ("swiggyinstamart",    "Groceries"),
    ("swiggy instamart",   "Groceries"),
    ("blinkit",            "Groceries"),
    ("zeptomarketplace",   "Groceries"),
    ("zepto",              "Groceries"),
    ("bigbasket",          "Groceries"),
    ("dmart",              "Groceries"),

    # Food & dining
    ("swiggy",             "Food"),   # (non-instamart Swiggy)
    ("zomato",             "Food"),
    ("chickhen",           "Food"),
    ("chick hen",          "Food"),
    ("meatmart",           "Food"),
    ("meat mart",          "Food"),
    ("gopizza",            "Food"),
    ("iyengarbread",       "Food"),
    ("iyengar bread",      "Food"),
    ("thindipotha",        "Food"),
    ("olivaclinic",        "Health"),  # (misplaced pattern, but let's handle)

    # Shopping
    ("flipkart",           "Shopping"),
    ("myntra",             "Shopping"),
    ("amazon",             "Shopping"),
    ("meesho",             "Shopping"),
    ("rebelmarketplace",   "Shopping"),
    ("rebel marketplace",  "Shopping"),
    ("smart point",        "Shopping"),
    ("smartpoint",         "Shopping"),
    ("shubham selection",  "Shopping"),

    # Health
    ("oliva",              "Health"),
    ("apollo",             "Health"),
    ("pharmeasy",          "Health"),
    ("1mg",                "Health"),
    ("netmeds",            "Health"),

    # Transport
    ("autope",             "Transport"),
    ("uber",               "Transport"),
    ("ola",                "Transport"),
    ("rapido",             "Transport"),
    ("irctc",              "Transport"),

    # Government / utilities
    ("khajana",            "Government"),
    ("department of finance", "Government"),
    ("bescom",             "Utilities"),
    ("bwssb",              "Utilities"),

    # Services / tech
    ("ctrlxtechnologies",  "Services"),
    ("ctrlx technologies", "Services"),
    ("ujoy",               "Entertainment"),
    ("bookmyshow",         "Entertainment"),
    ("netflix",            "Entertainment"),
    ("spotify",            "Entertainment"),
    ("hotstar",            "Entertainment"),
    ("prime video",        "Entertainment"),

    # Investment / savings
    ("groww",              "Investment"),
    ("zerodha",            "Investment"),
    ("indmoney",           "Investment"),
    ("kuvera",             "Investment"),
]

# Remark keywords (bank statement remark field) — much stronger signal
REMARK_RULES: list[tuple[str, str]] = [
    ("groceries",    "Groceries"),
    ("milk",         "Groceries"),
    ("eggs",         "Groceries"),
    ("vegetables",   "Groceries"),
    ("chicken",      "Food"),
    ("pizza",        "Food"),
    ("juice",        "Food"),
    ("coconut",      "Groceries"),
    ("dinner",       "Food"),
    ("lunch",        "Food"),
    ("breakfast",    "Food"),
    ("rapido",       "Transport"),
    ("uber",         "Transport"),
    ("ola",          "Transport"),
    ("auto",         "Transport"),
    ("cab",          "Transport"),
    ("petrol",       "Transport"),
    ("fuel",         "Transport"),
    ("gym",          "Health"),
    ("subscription", "Subscriptions"),
    ("rent",         "Housing"),
    ("emi",          "Loans"),
    ("ipo",          "Investment"),
    ("mutual fund",  "Investment"),
    ("phone repair", "Services"),
    ("mane",         "Housing"),  # 'mane' = house in Kannada, rent context
]


def rule_categorize(merchant_raw: str, remark: str | None = None) -> str:
    """Return category from Tier 1 rules. 'Uncategorized' if no match."""
    m = (merchant_raw or "").lower().replace(" ", "").replace(".", "").replace(",", "")
    m_full = (merchant_raw or "").lower()

    for needle, cat in MERCHANT_RULES:
        needle_key = needle.replace(" ", "")
        if needle_key in m or needle in m_full:
            return cat

    if remark:
        r = remark.lower()
        for needle, cat in REMARK_RULES:
            if needle in r:
                return cat

    return "Uncategorized"


if __name__ == "__main__":
    tests = [
        ("SWIGGYINSTAMART",           None,      "Groceries"),
        ("Blinkit",                   None,      "Groceries"),
        ("NagarajC",                  None,      "Uncategorized"),
        ("Flipkart Payments",         None,      "Shopping"),
        ("MYNTRA",                    None,      "Shopping"),
        ("CTRLXTECHNOLOGIESPRIVATELIMITED", None, "Services"),
        ("SANTHOSHKUMAR",             "coconut", "Groceries"),
        ("Mr KUMAR",                  "rapido",  "Transport"),
    ]
    for merchant, remark, expected in tests:
        got = rule_categorize(merchant, remark)
        ok = "✓" if got == expected else "✗"
        print(f"  {ok} {merchant!r:45s} + {str(remark)!r:12s} → {got!r} (expected {expected!r})")

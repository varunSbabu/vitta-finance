"""Tier 1 categorization — deterministic rules on merchant name.

Order of resolution:
1. User dictionary lookup (exact merchant_key match) — Tier 2, in main.py
2. Rules below — Tier 1
3. LLM fallback — Tier 3, in llm_categorize.py
4. Fall through to 'Uncategorized'
"""

from __future__ import annotations

# The fixed label set every tier must pick from. Keeping this centralized
# means the LLM tier can only ever return a category the rest of the app
# already knows how to render — no surprise labels from a model response.
CATEGORIES: list[str] = [
    "Groceries",
    "Food",
    "Shopping",
    "Health",
    "Transport",
    "Government",
    "Utilities",
    "Services",
    "Entertainment",
    "Investment",
    "Cash",
    "Income",
    "Subscriptions",
    "Housing",
    "Loans",
    "Transfers",
    "Uncategorized",
]

MERCHANT_RULES: list[tuple[str, str]] = [
    # Groceries / quick commerce
    ("swiggyinstamart", "Groceries"),
    ("swiggy instamart", "Groceries"),
    ("blinkit", "Groceries"),
    ("zeptomarketplace", "Groceries"),
    ("zepto", "Groceries"),
    ("bigbasket", "Groceries"),
    ("dmart", "Groceries"),
    # Food & dining
    ("swiggy", "Food"),
    ("zomato", "Food"),
    ("chai", "Food"),
    ("tea stall", "Food"),
    ("tea point", "Food"),
    ("coffee", "Food"),
    ("tiffin", "Food"),
    ("chickhen", "Food"),
    ("chick hen", "Food"),
    ("meatmart", "Food"),
    ("meat mart", "Food"),
    ("gopizza", "Food"),
    ("iyengarbread", "Food"),
    ("iyengar bread", "Food"),
    ("thindipotha", "Food"),
    # Shopping
    ("flipkart", "Shopping"),
    ("myntra", "Shopping"),
    ("amazon", "Shopping"),
    ("meesho", "Shopping"),
    ("rebelmarketplace", "Shopping"),
    ("rebel marketplace", "Shopping"),
    ("smart point", "Shopping"),
    ("smartpoint", "Shopping"),
    ("shubham selection", "Shopping"),
    # Health
    ("oliva", "Health"),
    ("apollo", "Health"),
    ("pharmeasy", "Health"),
    ("1mg", "Health"),
    ("netmeds", "Health"),
    # Transport
    ("autope", "Transport"),
    ("uber", "Transport"),
    ("ola", "Transport"),
    ("rapido", "Transport"),
    ("irctc", "Transport"),
    # Government / utilities
    ("khajana", "Government"),
    ("department of finance", "Government"),
    ("bescom", "Utilities"),
    ("bwssb", "Utilities"),
    # Services / tech
    ("ctrlxtechnologies", "Services"),
    ("ctrlx technologies", "Services"),
    ("ujoy", "Entertainment"),
    ("bookmyshow", "Entertainment"),
    ("netflix", "Entertainment"),
    ("spotify", "Entertainment"),
    ("hotstar", "Entertainment"),
    ("prime video", "Entertainment"),
    # Investment / savings
    ("groww", "Investment"),
    ("zerodha", "Investment"),
    ("indmoney", "Investment"),
    ("kuvera", "Investment"),
    # ATM / cash
    ("atm withdrawal", "Cash"),
    ("atm-nfs", "Cash"),
    ("cash wdl", "Cash"),
    # Bank / finance
    ("bank interest", "Income"),
    ("interest credit", "Income"),
]

REMARK_RULES: list[tuple[str, str]] = [
    ("groceries", "Groceries"),
    ("milk", "Groceries"),
    ("eggs", "Groceries"),
    ("vegetables", "Groceries"),
    ("chicken", "Food"),
    ("pizza", "Food"),
    ("juice", "Food"),
    ("coconut", "Groceries"),
    ("dinner", "Food"),
    ("lunch", "Food"),
    ("breakfast", "Food"),
    ("chai", "Food"),
    ("tea", "Food"),
    ("coffee", "Food"),
    ("snacks", "Food"),
    ("snack", "Food"),
    ("tiffin", "Food"),
    ("samosa", "Food"),
    ("vada", "Food"),
    ("dosa", "Food"),
    ("idli", "Food"),
    ("rapido", "Transport"),
    ("uber", "Transport"),
    ("ola", "Transport"),
    ("auto", "Transport"),
    ("cab", "Transport"),
    ("petrol", "Transport"),
    ("fuel", "Transport"),
    ("gym", "Health"),
    ("subscription", "Subscriptions"),
    ("rent", "Housing"),
    ("emi", "Loans"),
    ("ipo", "Investment"),
    ("mutual fund", "Investment"),
    ("phone repair", "Services"),
    ("mane", "Housing"),
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

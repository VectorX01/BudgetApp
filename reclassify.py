"""One-time reclassification of the Income rows, as approved 2026-09-20.

Two changes, both confined to rows currently typed ``Income``:

1. Merchant refunds and returns become ``Refund`` and take the category of the
   thing they reverse, so they offset that category's spend instead of counting
   as money earned. 34 rows, $1,506.37.
2. The rows that remain income get a real category in place of ``Other``:
   Salary, Gift, Tax refund, Cashback, Interest, Dividend, Award, Opening
   balance. 51 rows.

Categories were taken from the user's own tagging history rather than guessed:
45 of 51 Amazon rows are Shopping, 70 of 70 Patels rows are Groceries, 17 of 17
Subway rows are Dining. Two were decided by the user directly — Target refunds
to Shopping (its own history splits 29/23), and the NYU Health Insurance Refund
to Education, against the NYU Fee it partly reverses.

Nothing else in the sheet is touched, and no row is deleted or re-signed.
"""

from __future__ import annotations

import pandas as pd

# Matched in order; first hit wins. Keys are lowercase substrings of Description.
INCOME_RULES: list[tuple[str, str]] = [
    ("starting balance", "Opening balance"),
    ("nyu award", "Award"),
    ("igotanoffer", "Award"),
    ("tax refund", "Tax refund"),
    ("salary", "Salary"),
    ("nyu income", "Salary"),
    ("money from papa", "Gift"),
    ("zelle from", "Gift"),
    ("dividend", "Dividend"),
    ("interest", "Interest"),
    ("cashback", "Cashback"),
    ("cash reward", "Cashback"),
    ("daily cash", "Cashback"),
    ("reward", "Cashback"),
    ("offer", "Cashback"),
]

# Refund rules are consulted only when no income rule matched.
REFUND_RULES: list[tuple[str, str]] = [
    ("nyu health insurance", "Education"),   # reverses the NYU Fee (Education)
    ("hbomax", "Entertainment"),
    ("igniting", "Networking"),              # reverses the -15.00 EB charge
    ("astar", "Utilities"),                  # reverses the -70.76 PayPal charge
    ("fee reversal", "Utilities"),           # reverses Chase Service Fee -15.00
    ("txn reversal", "Utilities"),           # no matching charge; user-confirmed
    ("amazon", "Shopping"),
    ("target", "Shopping"),                  # user decision: 29/23 split
    ("patels", "Groceries"),
    ("big bazaar", "Groceries"),
    ("subway", "Dining"),
    ("shake shack", "Dining"),
]


def classify(description: str) -> tuple[str, str] | None:
    """Return (Transaction_Type, Category) for an income row, or None to skip."""
    text = str(description).strip().lower()
    for needle, category in INCOME_RULES:
        if needle in text:
            return "Income", category
    for needle, category in REFUND_RULES:
        if needle in text:
            return "Refund", category
    return None


def plan(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that would change, with their before and after values.

    Takes a prepared frame (see ``finance.prepare``) and returns only genuine
    changes, so re-running after the migration yields an empty plan.
    """
    changes = []
    for index, row in df[df["Type"] == "Income"].iterrows():
        result = classify(row["Description"])
        if result is None:
            continue
        new_type, new_category = result
        old_type = str(row["Transaction_Type"]).strip()
        old_category = str(row["Category"]).strip()
        if old_type == new_type and old_category == new_category:
            continue
        changes.append(
            {
                "row": index,
                "Date": row["Date"],
                "Description": row["Description"],
                "Amount": row["Amount"],
                "From": f"{old_type} / {old_category}",
                "To": f"{new_type} / {new_category}",
                "Transaction_Type": new_type,
                "Category": new_category,
            }
        )
    return pd.DataFrame(changes)


def unclassified(df: pd.DataFrame) -> pd.DataFrame:
    """Income rows no rule matched. These are left alone and reported."""
    mask = df["Type"] == "Income"
    unmatched = [
        index for index, row in df[mask].iterrows()
        if classify(row["Description"]) is None
    ]
    return df.loc[unmatched, ["Date", "Description", "Amount", "Card", "Category"]]


def apply_plan(raw: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of the raw sheet frame with the planned edits applied.

    Operates on the *raw* frame so the result can be written straight back to
    the sheet with its original seven columns and row order intact.
    """
    updated = raw.copy()
    for _, change in changes.iterrows():
        updated.at[change["row"], "Transaction_Type"] = change["Transaction_Type"]
        updated.at[change["row"], "Category"] = change["Category"]
    return updated

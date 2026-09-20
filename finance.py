"""Pure data logic for the budget tracker.

No Streamlit imports live here on purpose: everything below is a plain pandas
function so it can be tested against a snapshot of the real sheet without
credentials or a running app. ``app.py`` owns all presentation.

Sign convention (unchanged from the original sheet):
    Expense        negative     money spent
    Refund         positive     money returned; offsets the category it came from
    Income         positive     money earned or received
    Transfer (out) negative     money leaving an account
    Transfer (in)  positive     money arriving at another account

Every transfer is two rows summing to zero, so summing the whole sheet gives
true net worth. That property is load-bearing; nothing here may break it.
"""

from __future__ import annotations

import pandas as pd

COLUMNS = [
    "Date",
    "Description",
    "Amount",
    "Card",
    "Category",
    "Statement_Month",
    "Transaction_Type",
]

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_INDEX = {name: i + 1 for i, name in enumerate(MONTHS)}

# Canonical transaction types, plus the historical spellings they replace.
# Old rows are never rewritten; they are read through this table instead.
TYPE_ALIASES = {
    "Expense": "Expense",
    "Income": "Income",
    "Refund": "Refund",
    "Transfer (out)": "Transfer (out)",
    "Transfer (in)": "Transfer (in)",
    "Card Payment (Bank side)": "Transfer (out)",
    "Card Payment (Card side)": "Transfer (in)",
    "Card Payment(Card Side)": "Transfer (in)",  # 6 rows, typo variant
}

ENTRY_TYPES = ["Expense", "Income", "Refund", "Transfer"]

# Applied when writing a new row. Stored amounts already carry their sign.
SIGN = {
    "Expense": -1,
    "Refund": +1,
    "Income": +1,
    "Transfer (out)": -1,
    "Transfer (in)": +1,
}

TRANSFER_TYPES = ("Transfer (out)", "Transfer (in)")

# Accounts you hold money in, in display order.
ASSET_ACCOUNTS = [
    "Checking",
    "Savings",
    "Marcus HYSA",
    "Fidelity Cash Management",
    "Fidelity Brokerage",
    "Schwab Brokerage",
]
# Accounts you owe money on.
CARD_ACCOUNTS = ["Chase", "Amex", "Target", "Samsung Card"]
# Closed. History stays queryable; they do not get balance tiles.
ARCHIVED_ACCOUNTS = ["Apple Card", "Discover", "Splitwise"]
# Market-exposed: these are the ones a weekly valuation is worth logging for.
INVESTMENT_ACCOUNTS = ["Schwab Brokerage", "Fidelity Brokerage"]
# Where money goes to be put away. Checking and Savings are transactional —
# salary lands in them and bills leave from them — so cash resting there has
# not been set aside in any meaningful sense.
SAVINGS_ACCOUNTS = [
    "Marcus HYSA",
    "Fidelity Cash Management",
    "Fidelity Brokerage",
    "Schwab Brokerage",
]

EXPENSE_CATEGORIES = [
    "Dining", "Groceries", "Transit", "Rent", "Personal", "Travel",
    "Shopping", "Education", "Entertainment", "Utilities", "Donations",
    "Networking", "Immigration", "Other",
]
INCOME_CATEGORIES = [
    "Salary", "Gift", "Tax refund", "Cashback", "Interest", "Dividend",
    "Award", "Opening balance", "Other",
]
# Bookkeeping artifact rather than money earned, so it is excluded from "Earned".
NON_EARNED_CATEGORIES = ["Opening balance"]
# Below this much income in a month, a savings percentage is noise; show nothing.
RATE_FLOOR = 100.0

# How a month is defined. Statement is the default because that is when the
# money is felt: a July card swipe is not paid for until the August bill.
BASIS_COLUMN = {"statement": "Statement_Period", "calendar": "Month"}
BASIS_LABEL = {"statement": "Statement month", "calendar": "Calendar month"}

VALUATION_COLUMNS = ["Date", "Account", "Market_Value"]
VALUATIONS_WORKSHEET = "Valuations"


# ──────────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────────

def canonical_type(raw: object) -> str:
    """Map any historical Transaction_Type spelling onto a canonical one."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return "Expense"
    text = str(raw).strip()
    if text in TYPE_ALIASES:
        return TYPE_ALIASES[text]
    # Tolerate whitespace and casing drift without silently inventing a type.
    squashed = text.replace(" ", "").lower()
    for alias, canon in TYPE_ALIASES.items():
        if alias.replace(" ", "").lower() == squashed:
            return canon
    return "Expense"


def infer_period(date: pd.Timestamp, statement_month: object) -> pd.Period | None:
    """Resolve a bare month name to a real year using the transaction date.

    A statement falls in the same month as the transaction or shortly after it,
    so the correct year is the one that puts the statement 0-2 months ahead.
    Resolves 998 of the 1,001 rows in the current sheet; the rest are rows keyed
    in long after the fact and fall back to the transaction's own month.
    """
    if pd.isna(date):
        return None
    name = str(statement_month).strip() if statement_month is not None else ""
    month = MONTH_INDEX.get(name.title())
    if month is None:
        return pd.Period(year=date.year, month=date.month, freq="M")
    if month < date.month - 6:
        year = date.year + 1
    elif month > date.month + 6:
        year = date.year - 1
    else:
        year = date.year
    return pd.Period(year=year, month=month, freq="M")


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise a raw sheet read into the frame the rest of the app expects.

    Adds:
        Type              canonical Transaction_Type
        Date              real datetime
        Month             calendar month of the transaction  (money arithmetic)
        Statement_Period  statement month resolved to a year (billing views)
    """
    df = raw.copy()
    df = df.dropna(how="all")
    for column in COLUMNS:
        if column not in df.columns:
            df[column] = None

    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0.0)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df[df["Date"].notna()].copy()

    df["Type"] = df["Transaction_Type"].map(canonical_type)
    for column in ("Card", "Category", "Description"):
        df[column] = df[column].fillna("Other" if column != "Description" else "")
        df[column] = df[column].astype(str).str.strip()

    df["Month"] = df["Date"].dt.to_period("M")
    df["Statement_Period"] = [
        infer_period(date, month)
        for date, month in zip(df["Date"], df["Statement_Month"])
    ]
    return df.reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
# Balances
# ──────────────────────────────────────────────────────────────────────────────

def balances(df: pd.DataFrame) -> pd.Series:
    """Signed balance per account across all time."""
    if df.empty:
        return pd.Series(dtype="float64")
    return df.groupby("Card")["Amount"].sum()


def known_accounts() -> list[str]:
    return ASSET_ACCOUNTS + CARD_ACCOUNTS + ARCHIVED_ACCOUNTS


def unlisted_accounts(df: pd.DataFrame) -> list[str]:
    """Accounts present in the data but missing from every display list.

    Surfacing these is deliberate: an account that exists in the sheet must
    never be silently absent from the dashboard again.
    """
    return sorted(set(df["Card"].unique()) - set(known_accounts()))


def account_summary(df: pd.DataFrame) -> pd.DataFrame:
    """One row per account: balance, row count, and most recent activity."""
    if df.empty:
        return pd.DataFrame(columns=["Account", "Balance", "Rows", "Last activity"])
    grouped = df.groupby("Card").agg(
        Balance=("Amount", "sum"),
        Rows=("Amount", "size"),
        **{"Last activity": ("Date", "max")},
    )
    return grouped.reset_index().rename(columns={"Card": "Account"})


def net_worth(df: pd.DataFrame, valuations: pd.DataFrame | None = None) -> float:
    """Total net worth. Transfer pairs cancel, so this is simply the full sum.

    When a valuation exists for an investment account, its market value replaces
    the contributed-cash figure, since cost basis is not what the account is
    worth.
    """
    if df.empty:
        return 0.0
    total = float(df["Amount"].sum())
    for account, market_value in latest_valuations(valuations).items():
        basis = float(df.loc[df["Card"] == account, "Amount"].sum())
        total += market_value - basis
    return total


# ──────────────────────────────────────────────────────────────────────────────
# Monthly summary
# ──────────────────────────────────────────────────────────────────────────────

def monthly_summary(df: pd.DataFrame, basis: str = "statement") -> pd.DataFrame:
    """Earned / spent / saved per period, on either basis.

        earned   income, excluding bookkeeping-only opening balances
        spent    expenses net of refunds
        kept     earned - spent

    ``Kept`` is deliberately not called "saved". It measures new money retained
    this period, which is a different thing from money moved into a savings
    account: a transfer from Savings to Marcus HYSA relocates cash that was
    already earned and already kept in an earlier period. Counting it again
    here would double-count it. ``net_into_savings`` reports that movement
    separately.

    ``basis="statement"`` (the default) groups rows the way the card bills land,
    which is how the money is actually felt: a July swipe is not paid for until
    the August statement is settled. ``basis="calendar"`` groups by transaction
    date, which is what reconciling against a bank statement needs.

    Either basis is safe here. All three figures are built from Income, Expense
    and Refund rows only, so the transfer legs that straddle statement periods
    never enter the arithmetic — that residual can only reach a total that sums
    every row, which is ``net_worth_change`` and stays dated for that reason.
    """
    if df.empty:
        return pd.DataFrame(
            columns=["Period", "Earned", "Salary", "Spent", "Kept", "Kept %"]
        )

    column = BASIS_COLUMN[basis]
    keyed = df[df[column].notna()]
    income = keyed[keyed["Type"] == "Income"]
    earned = (
        income[~income["Category"].isin(NON_EARNED_CATEGORIES)]
        .groupby(column)["Amount"].sum()
    )
    salary = income[income["Category"] == "Salary"].groupby(column)["Amount"].sum()
    outgoing = keyed[keyed["Type"].isin(["Expense", "Refund"])]
    spent = -outgoing.groupby(column)["Amount"].sum()

    months = pd.period_range(keyed[column].min(), keyed[column].max(), freq="M")
    summary = pd.DataFrame(index=months)
    summary["Earned"] = earned.reindex(months).fillna(0.0)
    summary["Salary"] = salary.reindex(months).fillna(0.0)
    summary["Spent"] = spent.reindex(months).fillna(0.0)
    summary["Kept"] = summary["Earned"] - summary["Spent"]
    # A save rate computed against a near-zero month is noise, not information
    # (March 2026 earned $2.54 and would read -77,128%).
    summary["Kept %"] = (
        (summary["Kept"] / summary["Earned"]).where(summary["Earned"] >= RATE_FLOOR)
        * 100
    )
    return summary.rename_axis("Period").reset_index()


def accruing_period(df: pd.DataFrame, basis: str = "statement") -> pd.Period | None:
    """The period that is still filling up: the one holding the newest row.

    A period mid-flight is not comparable with a closed one — its income and
    its bills have arrived in different proportions — so the UI labels it and
    does not open on it.
    """
    if df.empty:
        return None
    return df.loc[df["Date"].idxmax(), BASIS_COLUMN[basis]]


def net_worth_change(df: pd.DataFrame) -> pd.Series:
    """Change in net worth per calendar month.

    Always dated, never by statement: this sums every row including transfer
    legs, and a statement label does not say when cash actually moved.
    """
    if df.empty:
        return pd.Series(dtype="float64")
    return df.groupby("Month")["Amount"].sum()


def net_worth_series(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative net worth by calendar month, from cost basis only."""
    if df.empty:
        return pd.DataFrame(columns=["Month", "Net worth"])
    monthly = df.groupby("Month")["Amount"].sum()
    months = pd.period_range(df["Month"].min(), df["Month"].max(), freq="M")
    series = monthly.reindex(months).fillna(0.0).cumsum()
    return pd.DataFrame({"Month": months, "Net worth": series.values})


def category_spend(df: pd.DataFrame) -> pd.Series:
    """Net spend per category: expenses less the refunds that offset them."""
    outgoing = df[df["Type"].isin(["Expense", "Refund"])]
    if outgoing.empty:
        return pd.Series(dtype="float64")
    return (-outgoing.groupby("Category")["Amount"].sum()).sort_values(ascending=False)


def net_into_savings(df: pd.DataFrame) -> float:
    """Net money put away into savings and investment pots over these rows.

    Net, not gross: a $2,400 transfer out of Marcus on the same day as a $2,400
    transfer in has put nothing away. This answers "did my long-term pots grow",
    which is the question a transfer to HYSA actually raises — and it is not the
    same question as ``Kept``.
    """
    return float(df[df["Card"].isin(SAVINGS_ACCOUNTS)]["Amount"].sum())


def net_debt_paid(df: pd.DataFrame) -> float:
    """Net reduction in card balances: payments made less new charges."""
    cards = CARD_ACCOUNTS + ARCHIVED_ACCOUNTS
    return float(df[df["Card"].isin(cards)]["Amount"].sum())


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio
# ──────────────────────────────────────────────────────────────────────────────

def prepare_valuations(raw: pd.DataFrame | None) -> pd.DataFrame:
    """Normalise the Valuations worksheet. Missing or empty is a valid state."""
    if raw is None or len(raw) == 0:
        return pd.DataFrame(columns=VALUATION_COLUMNS).astype(
            {"Date": "datetime64[ns]", "Account": "object", "Market_Value": "float64"}
        )
    df = raw.copy().dropna(how="all")
    for column in VALUATION_COLUMNS:
        if column not in df.columns:
            df[column] = None
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Market_Value"] = pd.to_numeric(df["Market_Value"], errors="coerce")
    df["Account"] = df["Account"].astype(str).str.strip()
    df = df[df["Date"].notna() & df["Market_Value"].notna()]
    return df[VALUATION_COLUMNS].sort_values("Date").reset_index(drop=True)


def latest_valuations(valuations: pd.DataFrame | None) -> dict[str, float]:
    """Most recent market value per account."""
    if valuations is None or valuations.empty:
        return {}
    latest = valuations.sort_values("Date").groupby("Account").tail(1)
    return dict(zip(latest["Account"], latest["Market_Value"]))


def cost_basis(df: pd.DataFrame, account: str, as_of: pd.Timestamp | None = None) -> float:
    """Cash contributed to an account (plus in-account income, less withdrawals)."""
    rows = df[df["Card"] == account]
    if as_of is not None:
        rows = rows[rows["Date"] <= as_of]
    return float(rows["Amount"].sum())


def portfolio_position(df: pd.DataFrame, valuations: pd.DataFrame) -> pd.DataFrame:
    """Current cost basis vs market value per investment account."""
    latest = latest_valuations(valuations)
    accounts = sorted(set(INVESTMENT_ACCOUNTS) | set(latest))
    records = []
    for account in accounts:
        basis = cost_basis(df, account)
        market = latest.get(account)
        # An account with no money in it and no valuation is not a position.
        if market is None and abs(basis) < 0.005:
            continue
        as_of = None
        if account in latest:
            rows = valuations[valuations["Account"] == account]
            as_of = rows["Date"].max()
        records.append(
            {
                "Account": account,
                "Contributed": basis,
                "Market value": market,
                "Unrealised": None if market is None else market - basis,
                "Return %": None if not market or not basis else (market - basis) / basis * 100,
                "Valued on": as_of,
            }
        )
    return pd.DataFrame(records)


def mtm_history(df: pd.DataFrame, valuations: pd.DataFrame, account: str) -> pd.DataFrame:
    """Week-over-week split of value change into contributions vs market movement.

    The number worth reading is ``Market gain``: how much the holdings moved on
    their own, with deposits taken out of the comparison.
    """
    rows = valuations[valuations["Account"] == account].sort_values("Date")
    records = []
    previous = None
    for _, row in rows.iterrows():
        date, market = row["Date"], float(row["Market_Value"])
        basis = cost_basis(df, account, as_of=date)
        if previous is None:
            # No earlier snapshot to compare against, so there is no weekly
            # movement and no weekly deposit figure either — repeating the cost
            # basis in the Deposits column just duplicates the column beside it.
            contributed = None
            change = None
            gain = None
        else:
            prev_date, prev_market = previous
            window = df[
                (df["Card"] == account)
                & (df["Date"] > prev_date)
                & (df["Date"] <= date)
            ]
            contributed = float(window["Amount"].sum())
            change = market - prev_market
            gain = change - contributed
        records.append(
            {
                "Date": date,
                "Market value": market,
                "Contributed": contributed,
                "Change": change,
                "Market gain": gain,
                "Cost basis": basis,
                "Unrealised": market - basis,
            }
        )
        previous = (date, market)
    return pd.DataFrame(records)


# ──────────────────────────────────────────────────────────────────────────────
# Integrity
# ──────────────────────────────────────────────────────────────────────────────

def unmatched_transfers(df: pd.DataFrame) -> pd.DataFrame:
    """Transfer legs with no counter-leg of the same amount.

    Every transfer should be two rows summing to zero. A leg without its partner
    means cash moved with nothing recorded on the other side.
    """
    legs = df[df["Type"].isin(TRANSFER_TYPES)].copy()
    if legs.empty:
        return legs
    keep = []
    for amount, group in legs.groupby(legs["Amount"].abs().round(2)):
        outgoing = group[group["Amount"] < 0]
        incoming = group[group["Amount"] > 0]
        surplus = outgoing if len(outgoing) > len(incoming) else incoming
        count = abs(len(outgoing) - len(incoming))
        if count:
            keep.append(surplus.sort_values("Date").tail(count))
    if not keep:
        return legs.iloc[0:0]
    return pd.concat(keep).sort_values("Date")


def integrity_report(
    df: pd.DataFrame, valuations: pd.DataFrame | None = None
) -> dict[str, object]:
    """Everything the Accounts tab needs to prove the books still reconcile.

    Assets use market value wherever a valuation exists, matching ``net_worth``.
    Without that the page would show one net worth in its header and a different
    one in its reconciliation strip.
    """
    legs = df[df["Type"].isin(TRANSFER_TYPES)]
    orphans = unmatched_transfers(df)
    latest = latest_valuations(valuations)
    assets = sum(
        latest.get(a, float(df.loc[df["Card"] == a, "Amount"].sum()))
        for a in ASSET_ACCOUNTS
    )
    debt = -sum(
        float(df.loc[df["Card"] == a, "Amount"].sum())
        for a in CARD_ACCOUNTS + ARCHIVED_ACCOUNTS
    )
    return {
        "assets": assets,
        "card_debt": debt,
        "net_worth": assets - debt,
        "transfer_residual": float(legs["Amount"].sum()),
        "orphans": orphans,
        "unlisted_accounts": unlisted_accounts(df),
        "valued_at_market": sorted(latest),
        "uncategorised_income": int(
            ((df["Type"] == "Income") & (~df["Category"].isin(INCOME_CATEGORIES)))
            .sum()
        ),
    }

"""Budget Tracker — a dashboard over a single Google Sheet.

Presentation only. All arithmetic lives in finance.py, the approved income
reclassification in reclassify.py, and the chart specs in charts.py, so the
numbers can be tested without a browser or credentials.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

import charts as C
import finance as F
import reclassify as R

st.set_page_config(page_title="Budget Tracker", layout="wide")

SHEET = "Sheet1"
CACHE_TTL = 300  # seconds; the sheet changes on human timescales, not machine ones
ALL_TIME = "All time"


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def theme_mode() -> str:
    """Which palette to draw with. Dark is a selected palette, not a flip.

    Order matters, and it is not the obvious one. Measured against Streamlit
    1.64:

        config theme.base = dark   -> get_option "dark",  context.theme "light"
        config unset, browser light-> get_option None,    context.theme "light"
        config unset, browser dark -> get_option None,    context.theme "dark"

    ``st.context.theme.type`` reports the *browser's* preference and ignores a
    configured theme, so trusting it first paints the light palette onto a dark
    app — near-black legend text on a near-black surface. The configured theme
    wins when there is one; the browser decides only when there is not.
    """
    try:
        configured = st.get_option("theme.base")
    except Exception:
        configured = None
    if configured in ("light", "dark"):
        return configured
    try:
        preferred = st.context.theme.type
    except Exception:
        preferred = None
    return preferred if preferred in ("light", "dark") else "light"


def money(value: float | None, places: int = 2) -> str:
    """Display money. The sign goes outside the currency symbol, never inside."""
    if value is None or pd.isna(value):
        return "—"
    return f"{'−' if value < 0 else ''}${abs(value):,.{places}f}"


def signed(value: float | None) -> str:
    """Money with an explicit sign, for prose."""
    if value is None or pd.isna(value):
        return "—"
    return f"{'+' if value >= 0 else '−'}${abs(value):,.2f}"


def delta(value: float | None) -> str | None:
    """A st.metric delta string.

    Streamlit decides the arrow direction and colour by looking for a leading
    ASCII hyphen, so the typographic minus used everywhere else in the UI would
    paint every decrease as a green rise. This is the one place that character
    matters more than the typography.
    """
    if value is None or pd.isna(value):
        return None
    return f"{'-' if value < 0 else '+'}${abs(value):,.2f}"


def percent(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:,.0f}%"


def label_period(period: pd.Period | None) -> str:
    return ALL_TIME if period is None else period.strftime("%b %Y")


def md(text: str) -> str:
    """Escape dollar signs for any Streamlit markdown surface.

    st.caption, st.markdown and st.warning read `$…$` as inline LaTeX, so two
    money figures in one string turn the text between them into italic maths and
    swallow both dollar signs. Escaping is harmless when there is only one, so
    every money-bearing string goes through here rather than being audited
    case by case.
    """
    return text.replace("$", r"\$")


# ──────────────────────────────────────────────────────────────────────────────
# Data
# ──────────────────────────────────────────────────────────────────────────────

conn = st.connection("gsheets", type=GSheetsConnection)


def read_ledger(ttl: int = CACHE_TTL) -> pd.DataFrame:
    return conn.read(worksheet=SHEET, ttl=ttl, usecols=list(range(7)))


def read_valuations(ttl: int = CACHE_TTL) -> pd.DataFrame | None:
    """The Valuations tab is optional — not having one yet is a normal state."""
    try:
        return conn.read(
            worksheet=F.VALUATIONS_WORKSHEET, ttl=ttl, usecols=list(range(3))
        )
    except Exception:
        return None


try:
    raw = read_ledger()
except Exception as error:  # a failed read is an error, never "no transactions"
    st.title("Budget Tracker")
    st.error(
        "Could not read the Google Sheet, so no figures below would be "
        f"trustworthy.\n\n**{type(error).__name__}:** {error}"
    )
    st.caption(
        "Check that the `gsheets` connection secret is set and that the sheet "
        "is still shared with the service account, then use Refresh."
    )
    if st.button("Refresh"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

df = F.prepare(raw)
valuations = F.prepare_valuations(read_valuations())
mode = theme_mode()

if df.empty:
    st.title("Budget Tracker")
    st.info(
        "The sheet is reachable but has no usable rows yet. Add your first "
        "transaction from the sidebar and this page will fill in."
    )
    st.stop()

worth_series = F.net_worth_series(df)
nw_change = F.net_worth_change(df)


# ──────────────────────────────────────────────────────────────────────────────
# Header — one period control drives every tab
# ──────────────────────────────────────────────────────────────────────────────

heading, spacer, refresh = st.columns([5, 3, 1])
heading.title("Budget Tracker")
with refresh:
    st.write("")
    if st.button("Refresh", width="stretch", help="Re-read the sheet now"):
        st.cache_data.clear()
        st.rerun()

def control_row():
    """A row that keeps its controls side by side at phone width.

    st.columns stacks below roughly 640px, which turned the period control into
    four full-width rows before any number was visible. Horizontal containers
    do not stack; the fallback keeps an older Streamlit from crashing outright.
    """
    try:
        return st.container(horizontal=True, vertical_alignment="center")
    except TypeError:
        return st.container()


with control_row():
    back = st.container()
    picker = st.container(width=190)
    forward = st.container()
    basis_col = st.container()

# One control, read before anything is computed, driving every tab. Statement
# month is the default because that is when a card purchase is actually paid.
basis = basis_col.radio(
    "Period basis",
    list(F.BASIS_LABEL),
    format_func=lambda key: F.BASIS_LABEL[key],
    horizontal=True,
    label_visibility="collapsed",
    help=(
        "Statement month groups each purchase into the bill that pays for it, "
        "so a late-July swipe counts against the August statement. Calendar "
        "month groups by transaction date, which is what you need when "
        "reconciling against a bank statement."
    ),
)
summary = F.monthly_summary(df, basis)
periods = list(summary["Period"])

# Open on the newest *closed* period: the newest one is still accruing, and
# landing on a half-filled cycle reads as a catastrophe rather than a month.
# Clamp on every run, since switching basis can change how many periods exist.
accruing = F.accruing_period(df, basis)
if "period_index" not in st.session_state:
    closed = [i for i, p in enumerate(periods) if p != accruing]
    st.session_state.period_index = closed[-1] if closed else len(periods) - 1
index = min(max(st.session_state.period_index, 0), len(periods) - 1)
if back.button("‹", disabled=index == 0, help="Previous month"):
    st.session_state.period_index = index - 1
    st.rerun()
if forward.button(
    "›", disabled=index >= len(periods) - 1, help="Next month"
):
    st.session_state.period_index = index + 1
    st.rerun()

chosen = picker.selectbox(
    "Period",
    options=list(range(len(periods))),
    index=index,
    format_func=lambda i: label_period(periods[i]),
    label_visibility="collapsed",
)
if chosen != index:
    st.session_state.period_index = chosen
    st.rerun()

period = periods[index]
basis_column = F.BASIS_COLUMN[basis]
month_rows = df[df[basis_column] == period]
previous = summary.iloc[index - 1] if index > 0 else None
current = summary.iloc[index]
st.caption(
    md(
        f"{len(df):,} transactions · {df['Date'].min():%d %b %Y} to "
        f"{df['Date'].max():%d %b %Y} · net worth {money(F.net_worth(df, valuations))}"
    )
)

if period == accruing:
    st.info(
        f"{label_period(period)} is still open — more transactions will land in "
        "it before it closes, so its totals are not yet comparable with the "
        "months before it.",
        icon=None,
    )

overview_tab, spending_tab, accounts_tab, portfolio_tab = st.tabs(
    ["Overview", "Spending", "Accounts", "Portfolio"]
)


# ──────────────────────────────────────────────────────────────────────────────
# Overview
# ──────────────────────────────────────────────────────────────────────────────

with overview_tab:
    a, b, c, d = st.columns(4)
    a.metric(
        "Earned",
        money(current["Earned"]),
        delta=None if previous is None else delta(current["Earned"] - previous["Earned"]),
    )
    other = current["Earned"] - current["Salary"]
    a.caption(
        md(
            f"salary {money(current['Salary'], 0)}"
            + (f" · other {money(other, 0)}" if abs(other) >= 1 else "")
        )
    )

    b.metric(
        "Spent",
        money(current["Spent"]),
        delta=None if previous is None else delta(current["Spent"] - previous["Spent"]),
        delta_color="inverse",
    )
    b.caption(f"expenses net of refunds · {F.BASIS_LABEL[basis].lower()}")

    c.metric(
        "Kept",
        money(current["Kept"]),
        delta=None if previous is None else delta(current["Kept"] - previous["Kept"]),
    )
    c.caption("new money this period — earned, less the bills")

    d.metric("Kept %", percent(current["Kept %"]))
    d.caption("—" if pd.isna(current["Kept %"]) else "of everything earned")

    # Moving cash into HYSA is not the same event as keeping new money, and
    # leaving it off the page invites exactly that confusion.
    put_away = F.net_into_savings(month_rows)
    debt_cut = F.net_debt_paid(month_rows)
    moved = []
    if abs(put_away) >= 1:
        moved.append(
            f"**{money(put_away)}** {'into' if put_away > 0 else 'out of'} "
            "savings and investment accounts"
        )
    if abs(debt_cut) >= 1:
        moved.append(
            f"**{money(abs(debt_cut))}** of card debt "
            f"{'paid down' if debt_cut > 0 else 'added'}"
        )
    if moved:
        st.caption(
            md(
                "Money moved between your own accounts this period: "
                + ", and ".join(moved)
                + ". That is cash you already had being relocated, so it is not "
                "counted in Kept — it was already earned in an earlier period."
            )
        )

    st.divider()

    left, right = st.columns([1, 1])
    with left:
        st.subheader("Net worth")
        st.caption(
            "Every month since the ledger opened, by transaction date — a "
            "running balance needs real dates. Cost basis unless a valuation exists."
        )
        st.altair_chart(
            C.net_worth(
                worth_series, mode, highlight=period if basis == "calendar" else None
            ),
            width="stretch",
            theme=None,
        )
    with right:
        st.subheader("Earned against spent")
        st.caption("The gap between the bars is what you kept.")
        st.altair_chart(
            C.earned_vs_spent(summary.tail(12), mode), width="stretch", theme=None
        )

    if previous is not None:
        now = F.category_spend(month_rows)
        before = F.category_spend(df[df["Month"] == periods[index - 1]])
        shift = (now.reindex(now.index.union(before.index)).fillna(0)
                 - before.reindex(now.index.union(before.index)).fillna(0))
        shift = shift[shift.abs() > 1]
        if not shift.empty:
            biggest = shift.abs().idxmax()
            direction = "more" if shift[biggest] > 0 else "less"
            st.caption(
                md(
                    f"Biggest move against {label_period(periods[index - 1])}: "
                    f"**{money(abs(shift[biggest]))} {direction}** on {biggest}."
                )
            )

    with st.expander("Month by month"):
        table = summary.copy()
        table["Period"] = table["Period"].map(label_period)
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            column_config={
                col: st.column_config.NumberColumn(col, format="dollar")
                for col in ("Earned", "Salary", "Spent", "Kept")
            }
            | {"Kept %": st.column_config.NumberColumn("Kept %", format="%.1f%%")},
        )


# ──────────────────────────────────────────────────────────────────────────────
# Spending
# ──────────────────────────────────────────────────────────────────────────────

with spending_tab:
    # Follows the header control, so this tab and the Overview can never
    # disagree about what a month is.
    outgoing = df[df["Type"].isin(["Expense", "Refund"])].copy()
    scoped = outgoing[outgoing[basis_column] == period]
    st.caption(
        f"{label_period(period)} · {F.BASIS_LABEL[basis].lower()}"
        + (
            f" · covering transactions dated {scoped['Date'].min():%d %b %Y} "
            f"to {scoped['Date'].max():%d %b %Y}"
            if not scoped.empty
            else ""
        )
    )
    outgoing = scoped

    other = "calendar" if basis == "statement" else "statement"
    spend_here = -outgoing["Amount"].sum()
    spend_other = -df[
        (df[F.BASIS_COLUMN[other]] == period) & df["Type"].isin(["Expense", "Refund"])
    ]["Amount"].sum()
    if abs(spend_here - spend_other) > 0.005:
        st.caption(
            md(
                f"On a {F.BASIS_LABEL[other].lower()} basis the same month comes "
                f"to {money(spend_other)}. The difference is purchases your cards "
                "billed to a neighbouring statement."
            )
        )

    with st.expander("Filters"):
        f1, f2 = st.columns(2)
        cards = sorted(outgoing["Card"].unique())
        categories = sorted(outgoing["Category"].unique())
        pick_cards = f1.multiselect("Accounts", cards, placeholder="All accounts")
        pick_cats = f2.multiselect("Categories", categories, placeholder="All categories")
        st.caption("Leave a filter empty to include everything.")
    if pick_cards:
        outgoing = outgoing[outgoing["Card"].isin(pick_cards)]
    if pick_cats:
        outgoing = outgoing[outgoing["Category"].isin(pick_cats)]

    expenses_only = outgoing[outgoing["Type"] == "Expense"]
    net_spend = -outgoing["Amount"].sum()
    refunded = outgoing.loc[outgoing["Type"] == "Refund", "Amount"].sum()

    m1, m2, m3 = st.columns(3)
    m1.metric("Net spend", money(net_spend))
    m1.caption(md(f"after {money(refunded)} of refunds") if refunded else "no refunds here")
    m2.metric("Purchases", f"{len(expenses_only):,}")
    m3.metric(
        "Average purchase",
        money(abs(expenses_only["Amount"].mean()) if len(expenses_only) else 0),
    )

    if outgoing.empty:
        st.info("Nothing matches those filters. Clear one to widen the view.")
    else:
        chart_col, table_col = st.columns([3, 2])
        with chart_col:
            st.subheader("By category")
            st.altair_chart(
                C.category_spend(F.category_spend(outgoing), mode),
                width="stretch",
                theme=None,
            )
        with table_col:
            st.subheader("By account")
            by_card = (-outgoing.groupby("Card")["Amount"].sum()).sort_values(
                ascending=False
            )
            st.dataframe(
                by_card.rename("Net spend").reset_index().rename(columns={"Card": "Account"}),
                width="stretch",
                hide_index=True,
                column_config={
                    "Net spend": st.column_config.NumberColumn("Net spend", format="dollar")
                },
            )

        st.subheader("Transactions")
        st.dataframe(
            outgoing.sort_values("Date", ascending=False)[
                ["Date", "Description", "Amount", "Card", "Category", "Type"]
            ],
            width="stretch",
            hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                "Amount": st.column_config.NumberColumn("Amount", format="dollar"),
            },
        )


# ──────────────────────────────────────────────────────────────────────────────
# Accounts
# ──────────────────────────────────────────────────────────────────────────────

with accounts_tab:
    report = F.integrity_report(df, valuations)
    balances = F.balances(df)

    r1, r2, r3 = st.columns(3)
    r1.metric("Assets", money(report["assets"]))
    r2.metric("Card debt", money(report["card_debt"]))
    r3.metric("Net worth", money(report["net_worth"]))
    valued = report["valued_at_market"]
    st.caption(
        md(
            f"{money(report['assets'])} held − {money(report['card_debt'])} owed = "
            f"{money(report['net_worth'])}. Every transfer pair cancels, so this is "
            "the sum of the whole sheet"
            + (f", with {', '.join(valued)} at market value." if valued else ".")
        )
    )

    st.divider()
    st.subheader("Where the money sits")
    for row_start in range(0, len(F.ASSET_ACCOUNTS), 3):
        columns = st.columns(3)
        for column, account in zip(columns, F.ASSET_ACCOUNTS[row_start : row_start + 3]):
            market = F.latest_valuations(valuations).get(account)
            column.metric(account, money(market if market is not None else balances.get(account, 0.0)))
            if market is not None:
                column.caption(
                    md(f"market value · {money(balances.get(account, 0.0))} contributed")
                )

    st.subheader("What you owe")
    for column, account in zip(st.columns(len(F.CARD_ACCOUNTS)), F.CARD_ACCOUNTS):
        column.metric(account, money(-balances.get(account, 0.0)))

    closed = [a for a in F.ARCHIVED_ACCOUNTS if a in balances.index]
    if closed:
        with st.expander(f"Closed accounts ({len(closed)})"):
            st.caption("Kept out of the tiles above; their history still counts everywhere else.")
            st.dataframe(
                F.account_summary(df).query("Account in @closed"),
                width="stretch",
                hide_index=True,
                column_config={
                    "Balance": st.column_config.NumberColumn("Balance", format="dollar"),
                    "Last activity": st.column_config.DateColumn(format="DD MMM YYYY"),
                },
            )

    st.divider()
    st.subheader("Integrity")
    orphans = report["orphans"]
    if report["unlisted_accounts"]:
        st.warning(
            "These accounts appear in the sheet but are not in any display list, "
            f"so they have no tile: {', '.join(report['unlisted_accounts'])}."
        )
    if len(orphans):
        st.warning(
            md(
                f"{len(orphans)} transfer legs have no counter-leg, "
                f"{money(abs(report['transfer_residual']))} in total. Net worth is "
                "still correct — the money really did leave — but these movements "
                "are invisible to the spending views."
            )
        )
        st.dataframe(
            orphans[["Date", "Description", "Amount", "Card"]],
            width="stretch",
            hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                "Amount": st.column_config.NumberColumn("Amount", format="dollar"),
            },
        )
    else:
        st.success("Every transfer pair balances.")

    plan = R.plan(df)
    with st.expander(
        f"Income reclassification ({len(plan)} rows pending)"
        if len(plan)
        else "Income reclassification (nothing pending)"
    ):
        if plan.empty:
            st.caption(
                "All income rows carry a real category and refunds are typed as "
                "refunds. Nothing to do."
            )
        else:
            st.caption(
                "Applies the approved mapping: merchant refunds become Refund rows "
                "that offset the category they reverse, and the remaining income "
                "rows get a real category instead of Other. Amounts are never "
                "touched, so net worth cannot change."
            )
            st.dataframe(
                plan[["Date", "Description", "Amount", "From", "To"]],
                width="stretch",
                hide_index=True,
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="DD MMM YYYY"),
                    "Amount": st.column_config.NumberColumn("Amount", format="dollar"),
                },
            )
            leftover = R.unclassified(df)
            if len(leftover):
                st.caption(f"{len(leftover)} income rows match no rule and stay as they are.")
            if st.button("Apply to the sheet", type="primary"):
                try:
                    fresh = read_ledger(ttl=0).dropna(how="all")
                    replan = R.plan(F.prepare(fresh))
                    conn.update(worksheet=SHEET, data=R.apply_plan(fresh, replan))
                except Exception as error:
                    st.error(f"Could not write to the sheet — {type(error).__name__}: {error}")
                else:
                    st.cache_data.clear()
                    st.success(f"Reclassified {len(replan)} rows.")
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio
# ──────────────────────────────────────────────────────────────────────────────

with portfolio_tab:
    position = F.portfolio_position(df, valuations)

    if valuations.empty:
        st.subheader("No valuations logged yet")
        st.markdown(
            md(
                "The balances elsewhere in this app are **cash you contributed**, "
                "not what your holdings are worth. Schwab reads "
                f"**{money(F.cost_basis(df, 'Schwab Brokerage'))}** because that is "
                "what you paid in — the market has had no say in that number.\n\n"
                "Log your account's total value once a week and this tab starts "
                "separating market movement from deposits."
            )
        )
    else:
        st.dataframe(
            position,
            width="stretch",
            hide_index=True,
            column_config={
                "Contributed": st.column_config.NumberColumn(format="dollar"),
                "Market value": st.column_config.NumberColumn(format="dollar"),
                "Unrealised": st.column_config.NumberColumn(format="dollar"),
                "Return %": st.column_config.NumberColumn(format="%.2f%%"),
                "Valued on": st.column_config.DateColumn(format="DD MMM YYYY"),
            },
        )

        valued = sorted(valuations["Account"].unique())
        account = (
            st.selectbox("Account", valued) if len(valued) > 1 else valued[0]
        )
        history = F.mtm_history(df, valuations, account)

        if len(history) < 2:
            st.info(
                "One valuation logged. A second one next week gives this tab a "
                "movement to report."
            )
        else:
            latest = history.iloc[-1]
            g1, g2, g3 = st.columns(3)
            g1.metric("Market value", money(latest["Market value"]))
            g2.metric("Unrealised", signed(latest["Unrealised"]))
            g3.metric("Last week's movement", signed(latest["Market gain"]))
            g3.caption("deposits excluded — this is the market alone")

            left, right = st.columns([3, 2])
            with left:
                st.subheader("Value against what you put in")
                st.caption("The gap between the two lines is your gain.")
                st.altair_chart(
                    C.market_vs_basis(history, mode), width="stretch", theme=None
                )
            with right:
                st.subheader("Weekly movement")
                st.caption("Change in value with deposits taken out.")
                st.altair_chart(
                    C.weekly_gain(history, mode), width="stretch", theme=None
                )

        st.dataframe(
            history,
            width="stretch",
            hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn("Week of", format="DD MMM YYYY"),
                "Market value": st.column_config.NumberColumn(format="dollar"),
                "Contributed": st.column_config.NumberColumn("Deposits", format="dollar"),
                "Change": st.column_config.NumberColumn(format="dollar"),
                "Market gain": st.column_config.NumberColumn(format="dollar"),
                "Cost basis": st.column_config.NumberColumn(format="dollar"),
                "Unrealised": st.column_config.NumberColumn(format="dollar"),
            },
        )

    st.divider()
    st.subheader("Log this week's values")
    with st.form("valuation_form", clear_on_submit=True):
        columns = st.columns([2, 3, 2])
        valued_on = columns[0].date_input("Date", date.today())
        accounts = columns[1].multiselect(
            "Accounts", F.INVESTMENT_ACCOUNTS, default=F.INVESTMENT_ACCOUNTS[:1]
        )
        st.caption("Enter the total value your broker shows, not a per-holding figure.")
        amounts = {
            account: st.number_input(
                f"{account} market value", min_value=0.0, step=0.01, format="%.2f"
            )
            for account in accounts
        }
        if st.form_submit_button("Save valuations", type="primary"):
            rows = [
                {
                    "Date": valued_on.strftime("%Y-%m-%d"),
                    "Account": account,
                    "Market_Value": value,
                }
                for account, value in amounts.items()
                if value > 0
            ]
            if not rows:
                st.warning("Enter a value above zero for at least one account.")
            else:
                try:
                    existing = read_valuations(ttl=0)
                    base = (
                        pd.DataFrame(columns=F.VALUATION_COLUMNS)
                        if existing is None
                        else existing.dropna(how="all")
                    )
                    conn.update(
                        worksheet=F.VALUATIONS_WORKSHEET,
                        data=pd.concat([base, pd.DataFrame(rows)], ignore_index=True)[
                            F.VALUATION_COLUMNS
                        ],
                    )
                except Exception as error:
                    st.error(
                        f"Could not write the valuations — {type(error).__name__}: {error}\n\n"
                        f"If the tab does not exist yet, add a worksheet named "
                        f"`{F.VALUATIONS_WORKSHEET}` with the headers "
                        f"`{'`, `'.join(F.VALUATION_COLUMNS)}` and try again."
                    )
                else:
                    st.cache_data.clear()
                    st.success(f"Logged {len(rows)} valuation(s).")
                    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar — entry
# ──────────────────────────────────────────────────────────────────────────────

def statement_choices(around: date) -> list[pd.Period]:
    centre = pd.Period(year=around.year, month=around.month, freq="M")
    return [centre - 1, centre, centre + 1]


def append_rows(rows: list[dict]) -> None:
    """Re-read before writing so a direct edit to the sheet is never clobbered."""
    fresh = read_ledger(ttl=0).dropna(how="all")
    combined = pd.concat([fresh, pd.DataFrame(rows)], ignore_index=True)
    conn.update(worksheet=SHEET, data=combined[list(fresh.columns)])


with st.sidebar:
    st.subheader("Add transaction")
    entry_type = st.selectbox("Type", F.ENTRY_TYPES)
    st.caption(
        {
            "Expense": "Money spent.",
            "Income": "Money earned or received.",
            "Refund": "A return or credit. Offsets the category it reverses.",
            "Transfer": "Moving money between your own accounts — including "
            "paying off a card. Both sides are written for you.",
        }[entry_type]
    )

    # Date sits outside the form so the statement-month options track it. Inside
    # a form nothing reruns until submit, which would offer months chosen for
    # whatever date was showing when the form last rendered.
    when = st.date_input("Date", date.today())

    with st.form("entry_form", clear_on_submit=True):
        description = st.text_input("Description")
        amount = st.number_input("Amount", min_value=0.0, step=0.01, format="%.2f")

        all_accounts = F.ASSET_ACCOUNTS + F.CARD_ACCOUNTS
        source = destination = account = None
        category = "Other"

        if entry_type == "Transfer":
            source = st.selectbox("From", F.ASSET_ACCOUNTS)
            destination = st.selectbox("To", [a for a in all_accounts], index=len(F.ASSET_ACCOUNTS))
        else:
            account = st.selectbox("Account", all_accounts)
            category = st.selectbox(
                "Category",
                F.INCOME_CATEGORIES if entry_type == "Income" else F.EXPENSE_CATEGORIES,
            )

        choices = statement_choices(when if isinstance(when, date) else date.today())
        statement = st.selectbox(
            "Statement month", choices, index=1, format_func=label_period
        )
        submitted = st.form_submit_button("Add", type="primary", width="stretch")

    if submitted:
        if amount <= 0:
            st.error("Enter an amount above zero.")
        elif entry_type == "Transfer" and source == destination:
            st.error("Pick two different accounts.")
        else:
            statement_name = F.MONTHS[statement.month - 1]
            base = {
                "Date": when.strftime("%Y-%m-%d"),
                "Description": description.strip() or entry_type,
                "Statement_Month": statement_name,
            }
            if entry_type == "Transfer":
                rows = [
                    {**base, "Amount": -amount, "Card": source,
                     "Category": "Other", "Transaction_Type": "Transfer (out)"},
                    {**base, "Amount": amount, "Card": destination,
                     "Category": "Other", "Transaction_Type": "Transfer (in)"},
                ]
            else:
                rows = [
                    {
                        **base,
                        "Amount": amount * F.SIGN[entry_type],
                        "Card": account,
                        "Category": category,
                        "Transaction_Type": entry_type,
                    }
                ]
            try:
                append_rows(rows)
            except Exception as error:
                st.error(f"Could not save — {type(error).__name__}: {error}")
            else:
                st.cache_data.clear()
                st.success(
                    "Transfer recorded on both sides."
                    if entry_type == "Transfer"
                    else "Transaction recorded."
                )
                st.rerun()

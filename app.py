import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Personal Finance Tracker", layout="wide")
st.title("📊 Expense & Tally Tracker")

COLUMNS = ["Date", "Description", "Amount", "Card", "Category", "Statement_Month", "Transaction_Type"]

# Sign convention:
#   Expense                  → negative  (wealth goes down)
#   Income                   → positive  (wealth goes up)
#   Card Payment (Bank side) → negative  (cash leaves Savings/Checking)
#   Card Payment (Card side) → positive  (cancels the bank side → net $0)
SIGN_MAP = {
    "Expense":                  -1,
    "Income":                   +1,
    "Card Payment (Bank side)": -1,
    "Card Payment (Card side)": +1,
}

# ── 1. Connect ────────────────────────────────────────────────────────────────
conn = st.connection("gsheets", type=GSheetsConnection)

# ── 2. Fetch & migrate ────────────────────────────────────────────────────────
try:
    df = conn.read(worksheet="Sheet1", ttl=5, usecols=list(range(7)))
    df = df.dropna(how="all")
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)

    # Backfill rows that predate the Transaction_Type column
    df["Transaction_Type"] = df["Transaction_Type"].fillna("Expense")

    # Migration: old Expense rows were stored as positive → flip to negative
    # New rows are stored negative already, so this only affects old data
    old_expense_mask = (df["Transaction_Type"] == "Expense") & (df["Amount"] > 0)
    df.loc[old_expense_mask, "Amount"] = df.loc[old_expense_mask, "Amount"] * -1

except Exception as e:
    st.warning(f"Could not load data: {e}")
    df = pd.DataFrame(columns=COLUMNS)

# ── 3. Sidebar: Entry Form ────────────────────────────────────────────────────
with st.sidebar:
    st.header("Add New Transaction")
    with st.form("entry_form", clear_on_submit=True):
        date = st.date_input("Transaction Date", datetime.now())
        desc = st.text_input("Description (e.g., Starbucks)")
        amount = st.number_input("Amount ($) — always enter as positive", min_value=0.0, step=0.01, value=0.0)
        txn_type = st.selectbox("Transaction Type", [
            "Expense",
            "Income",
            "Card Payment (Bank side)",   # cash leaving Savings/Checking
            "Card Payment (Card side)",   # clears the card balance
        ])
        card = st.selectbox("Card / Account", [
            "Chase", "Amex", "Discover", "Apple Card",
            "Target", "Checking", "Savings", "Splitwise", "Other"
        ])
        category = st.selectbox("Category", [
            "Dining", "Groceries", "Transit", "Rent", "Personal",
            "Shopping", "Education", "Entertainment", "Utilities", "Other"
        ])
        statement_month = st.selectbox("Assign to Statement Month", [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"
        ])
        submit = st.form_submit_button("Add to Tracker")

    if submit:
        signed_amount = amount * SIGN_MAP[txn_type]
        new_row = pd.DataFrame([{
            "Date":             date.strftime("%Y-%m-%d"),
            "Description":      desc,
            "Amount":           signed_amount,
            "Card":             card,
            "Category":         category,
            "Statement_Month":  statement_month,
            "Transaction_Type": txn_type,
        }])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        try:
            conn.update(worksheet="Sheet1", data=updated_df)
            st.success("Transaction recorded!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save: {e}")

    st.divider()
    st.caption("""
💡 **How to log a card payment (2 entries that cancel out):**

1. Card: **Savings** · Type: `Card Payment (Bank side)` · $200 → stored as −$200
2. Card: **Chase** · Type: `Card Payment (Card side)` · $200 → stored as +$200

Net effect on any aggregate view: **$0** ✓
    """)

# ── 4. Main Dashboard ─────────────────────────────────────────────────────────
if df.empty or df["Statement_Month"].dropna().empty:
    st.info("No transactions yet. Add one using the sidebar!")
else:

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1 — SPENDING
    # Only Expense rows. Card payments never enter this view,
    # so filtering by a specific card will never zero out your totals.
    # ═══════════════════════════════════════════════════════════════════════════
    st.header("💸 Section 1 — Spending")
    st.caption("Expense rows only. Card payments are excluded so totals are never zeroed out.")

    expense_df = df[df["Transaction_Type"] == "Expense"].copy()

    f1, f2, f3 = st.columns(3)
    with f1:
        months_s1 = ["All"] + sorted(expense_df["Statement_Month"].dropna().unique().tolist())
        selected_month_s1 = st.selectbox("Statement Month", months_s1, key="s1_month")
    with f2:
        cards_available = sorted(expense_df["Card"].dropna().unique().tolist())
        selected_cards = st.multiselect("Cards", cards_available, default=cards_available, key="s1_cards")
    with f3:
        cats_available = sorted(expense_df["Category"].dropna().unique().tolist())
        selected_cats = st.multiselect("Categories", cats_available, default=cats_available, key="s1_cats")

    filtered_expense = expense_df.copy()
    if selected_month_s1 != "All":
        filtered_expense = filtered_expense[filtered_expense["Statement_Month"] == selected_month_s1]
    filtered_expense = filtered_expense[filtered_expense["Card"].isin(selected_cards)]
    filtered_expense = filtered_expense[filtered_expense["Category"].isin(selected_cats)]

    # Amounts are stored negative — abs() for display
    total_spent = filtered_expense["Amount"].sum()
    count       = len(filtered_expense)
    avg         = total_spent / count if count > 0 else 0

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Spent",       f"${abs(total_spent):,.2f}")
    m2.metric("Transaction Count", count)
    m3.metric("Avg. Transaction",  f"${abs(avg):,.2f}")

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.subheader("Spending by Card")
        if not filtered_expense.empty:
            st.bar_chart(filtered_expense.groupby("Card")["Amount"].sum().abs())
        else:
            st.write("No data")
    with chart_col2:
        st.subheader("Spending by Category")
        if not filtered_expense.empty:
            st.bar_chart(filtered_expense.groupby("Category")["Amount"].sum().abs())
        else:
            st.write("No data")

    st.subheader("Expense Transactions")
    st.dataframe(
        filtered_expense.sort_values("Date", ascending=False),
        use_container_width=True,
        column_config={"Amount": st.column_config.NumberColumn("Amount", format="$%.2f")},
    )

    st.divider()

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2 — NET CASH FLOW
    # All rows included. No card/category filter here — filtering by card
    # would break the math since payment pairs would be split across accounts.
    # Signs handle everything: payment pairs cancel to $0 automatically.
    # ═══════════════════════════════════════════════════════════════════════════
    st.header("🏦 Section 2 — Net Cash Flow")
    st.caption("All rows. Card payment pairs cancel to $0. Sum everything → your true net position.")

    months_s2 = ["All"] + sorted(df["Statement_Month"].dropna().unique().tolist())
    selected_month_s2 = st.selectbox("Statement Month", months_s2, key="s2_month")

    cashflow_df = df.copy()
    if selected_month_s2 != "All":
        cashflow_df = cashflow_df[cashflow_df["Statement_Month"] == selected_month_s2]

    income = cashflow_df[cashflow_df["Transaction_Type"] == "Income"]["Amount"].sum()   # positive
    spent  = cashflow_df[cashflow_df["Transaction_Type"] == "Expense"]["Amount"].sum()  # negative
    net    = cashflow_df["Amount"].sum()                                                 # income - expenses

    n1, n2, n3 = st.columns(3)
    n1.metric("Total Income", f"${income:,.2f}")
    n2.metric("Total Spent",  f"${abs(spent):,.2f}")
    n3.metric("Net",          f"${net:,.2f}")

    st.subheader("All Transactions")
    st.dataframe(
        cashflow_df.sort_values("Date", ascending=False),
        use_container_width=True,
        column_config={
            "Amount":           st.column_config.NumberColumn("Amount", format="$%.2f"),
            "Transaction_Type": st.column_config.TextColumn("Type"),
        },
    )
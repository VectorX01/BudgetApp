import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Personal Finance Tracker", layout="wide")
st.title("📊 Expense & Tally Tracker")

COLUMNS = ["Date", "Description", "Amount", "Card", "Category", "Statement_Month"]

# 1. Connect to Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# 2. Fetch existing data
try:
    df = conn.read(worksheet="Sheet1", ttl=5, usecols=list(range(6)))
    df = df.dropna(how="all") 
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
    # Ensure Amount is numeric for math operations
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce").fillna(0)
except Exception as e:
    st.warning(f"Could not load data: {e}")
    df = pd.DataFrame(columns=COLUMNS)

# 3. Sidebar: Quick Entry Form
with st.sidebar:
    st.header("Add New Expense")
    with st.form("entry_form", clear_on_submit=True):
        date = st.date_input("Transaction Date", datetime.now())
        desc = st.text_input("Description (e.g., Starbucks)")
        amount = st.number_input("Amount ($) — negative for income/payment", min_value=None, step=0.01, value=0.0)
        card = st.selectbox("Card Used", ["Chase", "Amex", "Discover", "Apple Card","Target","Checking","Savings","Splitwise","Other"])
        category = st.selectbox("Category", ["Dining", "Groceries", "Transit", "Rent", "Personal","Shopping","Education","Entertainment","Utilities","Other"])
        statement_month = st.selectbox("Assign to Statement Month",
                                       ["January", "February", "March", "April", "May", "June",
                                        "July", "August", "September", "October", "November", "December"])
        submit = st.form_submit_button("Add to Tracker")

    if submit:
        new_row = pd.DataFrame([{
            "Date": date.strftime("%Y-%m-%d"),
            "Description": desc,
            "Amount": amount,
            "Card": card,
            "Category": category,
            "Statement_Month": statement_month
        }])
        updated_df = pd.concat([df, new_row], ignore_index=True)
        try:
            conn.update(worksheet="Sheet1", data=updated_df)
            st.success("Transaction recorded!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save: {e}")

# 4. Main Dashboard & Filtering Logic
if df.empty or df["Statement_Month"].dropna().empty:
    st.info("No transactions yet. Add one using the sidebar!")
else:
    st.header("🔍 Filter & Tally")
    
    # Create filter layout
    f1, f2, f3 = st.columns(3)
    
    with f1:
        months_available = ["All"] + sorted(df["Statement_Month"].dropna().unique().tolist())
        selected_month = st.selectbox("Statement Month", months_available)
        
    with f2:
        cards_available = sorted(df["Card"].dropna().unique().tolist())
        selected_cards = st.multiselect("Cards", cards_available, default=cards_available)
        
    with f3:
        cats_available = sorted(df["Category"].dropna().unique().tolist())
        selected_cats = st.multiselect("Categories", cats_available, default=cats_available)

    # Apply Filters
    filtered_df = df.copy()
    if selected_month != "All":
        filtered_df = filtered_df[filtered_df["Statement_Month"] == selected_month]
    
    filtered_df = filtered_df[filtered_df["Card"].isin(selected_cards)]
    filtered_df = filtered_df[filtered_df["Category"].isin(selected_cats)]

    # Metrics Display
    m1, m2, m3 = st.columns(3)
    total_val = filtered_df["Amount"].sum()
    m1.metric("Net Total", f"${total_val:,.2f}")
    m2.metric("Transaction Count", len(filtered_df))
    # Shows the average spend per transaction in this filtered view
    avg_spend = total_val / len(filtered_df) if len(filtered_df) > 0 else 0
    m3.metric("Avg. Transaction", f"${avg_spend:,.2f}")

    # Charts Section
    chart_col1, chart_col2 = st.columns(2)
    
    with chart_col1:
        st.subheader("Spending by Card")
        if not filtered_df.empty:
            card_data = filtered_df.groupby("Card")["Amount"].sum()
            st.bar_chart(card_data)
        else:
            st.write("No data for chart")

    with chart_col2:
        st.subheader("Spending by Category")
        if not filtered_df.empty:
            cat_data = filtered_df.groupby("Category")["Amount"].sum()
            st.bar_chart(cat_data)
        else:
            st.write("No data for chart")

    st.divider()
    st.subheader("Filtered Transactions")
    st.dataframe(filtered_df, use_container_width=True)
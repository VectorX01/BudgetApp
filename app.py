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
    df = df.dropna(how="all")  # Remove completely empty rows GSheets sometimes returns
    # Ensure all expected columns exist
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
except Exception as e:
    st.warning(f"Could not load data: {e}")
    df = pd.DataFrame(columns=COLUMNS)

# 3. Sidebar: Quick Entry Form
with st.sidebar:
    st.header("Add New Expense")
    with st.form("entry_form", clear_on_submit=True):
        date = st.date_input("Transaction Date", datetime.now())
        desc = st.text_input("Description (e.g., Starbucks)")
        amount = st.number_input("Amount ($)", min_value=0.0, step=0.01)
        card = st.selectbox("Card Used", ["Chase Sapphire", "Amex Gold", "Citi Custom", "Apple Card"])
        category = st.selectbox("Category", ["Dining", "Groceries", "Transit", "Rent", "Personal"])
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

# 4. Main Dashboard Analytics
if df.empty or df["Statement_Month"].dropna().empty:
    st.info("No transactions yet. Add one using the sidebar!")
else:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Monthly Tally (By Statement)")
        months_available = df["Statement_Month"].dropna().unique().tolist()
        selected_month = st.selectbox("Filter by Statement Month", months_available)
        monthly_df = df[df["Statement_Month"] == selected_month].copy()
        monthly_df["Amount"] = pd.to_numeric(monthly_df["Amount"], errors="coerce").fillna(0)
        total = monthly_df["Amount"].sum()
        st.metric(label=f"Total for {selected_month}", value=f"${total:,.2f}")
        st.dataframe(monthly_df, use_container_width=True)

    with col2:
        st.subheader("Spend by Card")
        card_sum = monthly_df.groupby("Card")["Amount"].sum()
        st.bar_chart(card_sum)

    st.divider()
    st.subheader("Raw Transaction History")
    st.dataframe(df, use_container_width=True)
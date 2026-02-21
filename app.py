import streamlit as st
from sys import exit
from streamlit_gsheets import GSheetsConnection # Note the underscores here
import pandas as pd
from datetime import datetime
st.set_page_config(page_title="Personal Finance Tracker", layout="wide")

st.title("📊 Expense & Tally Tracker")

# 1. Connect to Google Sheets
conn = st.connection("gsheets", type=GSheetsConnection)

# 2. Fetch existing data
df = conn.read(ttl="0") # Set ttl=0 to always get fresh data

# 3. Sidebar: Quick Entry Form
with st.sidebar:
    st.header("Add New Expense")
    with st.form("entry_form", clear_on_submit=True):
        date = st.date_input("Transaction Date", datetime.now())
        desc = st.text_input("Description (e.g., Starbucks)")
        amount = st.number_input("Amount ($)", min_value=0.0, step=0.01)
        card = st.selectbox("Card Used", ["Chase Sapphire", "Amex Gold", "Citi Custom", "Apple Card"])
        category = st.selectbox("Category", ["Dining", "Groceries", "Transit", "Rent", "Personal"])
        
        # LOGIC: Custom Statement Month Selection
        # Helps you assign a Jan expense to a Feb tally if needed
        statement_month = st.selectbox("Assign to Statement Month", 
                                     ["January", "February", "March", "April", "May", "June", 
                                      "July", "August", "September", "October", "November", "December"])
        
        submit = st.form_submit_button("Add to Tracker")

    if submit:
        new_data = pd.DataFrame([{
            "Date": date.strftime("%Y-%m-%d"),
            "Description": desc,
            "Amount": amount,
            "Card": card,
            "Category": category,
            "Statement_Month": statement_month
        }])
        updated_df = pd.concat([df, new_data], ignore_index=True)
        conn.update(data=updated_df)
        st.success("Transaction recorded!")
        st.rerun()

# 4. Main Dashboard Analytics
col1, col2 = st.columns(2)

with col1:
    st.subheader("Monthly Tally (By Statement)")
    selected_month = st.selectbox("Filter by Statement Month", df["Statement_Month"].unique())
    monthly_df = df[df["Statement_Month"] == selected_month]
    total = monthly_df["Amount"].sum()
    st.metric(label=f"Total for {selected_month}", value=f"${total:,.2f}")
    st.dataframe(monthly_df, use_container_width=True)

with col2:
    st.subheader("Spend by Card")
    card_sum = monthly_df.groupby("Card")["Amount"].sum()
    st.bar_chart(card_sum)

st.divider()
st.subheader("Raw Transaction History")
st.write(df)
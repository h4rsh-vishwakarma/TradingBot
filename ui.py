import streamlit as st
import pandas as pd
import sqlite3
import os
from bot.client import get_client
from bot.orders import place_order # Using your renamed function
from storage.jsonl_queue import read_jsonl

st.set_page_config(page_title="Binance Futures Bot", page_icon="📈", layout="wide")

st.title("🚀 Binance Futures Trader & Monitor")

# --- PATHS ---
QUEUE_FILE = "storage/tradingview_signals_queue.jsonl"
DLQ_FILE = "storage/dead_letter.jsonl"
DB_PATH = "storage/idempotency.db"

# Sidebar for Account Info
with st.sidebar:
    st.header("Account Status")
    try:
        client = get_client()
        acc = client.futures_account()
        st.success("Connected to Testnet")
        st.metric("Wallet Balance", f"{float(acc['totalWalletBalance']):.2f} USDT")
    except Exception as e:
        st.error(f"Connection Error: {e}")
    
    st.divider()
    if st.button('🔄 Refresh Data'):
        st.rerun()

# --- Main Layout: Tabs ---
tab1, tab2, tab3 = st.tabs(["Manual Trading", "Signal Logs", "System Health"])

with tab1:
    with st.form("order_form"):
        col1, col2 = st.columns(2)
        with col1:
            symbol = st.text_input("Symbol", value="BTCUSDT")
            side = st.selectbox("Side", ["BUY", "SELL"])
        with col2:
            order_type = st.selectbox("Order Type", ["MARKET", "LIMIT"])
            quantity = st.number_input("Quantity", min_value=0.001, step=0.001, format="%.3f")

        price = st.number_input("Limit Price", min_value=0.0) if order_type == "LIMIT" else None
        submit = st.form_submit_button("Place Order")

    if submit:
        with st.spinner("Executing order..."):
            result = place_order(client, symbol, side, order_type, quantity, price)
            if result:
                st.balloons()
                st.success(f"Order Placed! ID: {result['orderId']}")
                st.json(result)
            else:
                st.error("Order Failed. Check terminal for details.")

with tab2:
    st.subheader("Last 10 Signals from TradingView")
    signals = read_jsonl(QUEUE_FILE)
    if signals:
        # Convert to DataFrame for better viewing
        df_signals = pd.DataFrame(signals)
        st.dataframe(df_signals.tail(10), use_container_width=True)
    else:
        st.info("Waiting for first signal from Webhook...")

with tab3:
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.subheader("🛡️ Processed History")
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            df_db = pd.read_sql_query("SELECT * FROM processed_signals", conn)
            st.write(f"Unique Signals Processed: **{len(df_db)}**")
            st.dataframe(df_db.tail(10), use_container_width=True)
            conn.close()
    
    with col_b:
        st.subheader("⚠️ Dead-Letter Queue (Errors)")
        errors = read_jsonl(DLQ_FILE)
        if errors:
            st.warning(f"Found {len(errors)} failed signals.")
            st.dataframe(pd.DataFrame(errors), use_container_width=True)
        else:
            st.success("No system errors found!")
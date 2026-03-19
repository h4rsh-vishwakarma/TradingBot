import streamlit as st
import pandas as pd
import psutil
import subprocess
import os
import sys
import gc
import time
from io import StringIO
from datetime import datetime

# --- PATH FIX: Ensure we are in the project root ---
PROJECT_ROOT = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot"
sys.path.append(PROJECT_ROOT)

def clear_memory():
    """Forcibly free up unused RAM"""
    gc.collect()

def get_optimized_logs(file_path, n=20):
    """Memory efficient: Reads only last N lines without loading full file"""
    try:
        if os.path.exists(file_path):
            # Using Linux 'tail' to avoid loading large CSV into RAM
            proc = subprocess.Popen(['tail', f'-n', str(n), file_path], stdout=subprocess.PIPE)
            output, _ = proc.communicate()
            
            # Read only the snippet into DataFrame
            df = pd.read_csv(StringIO(output.decode()), names=['ID', 'Timestamp', 'Event', 'Details'])
            return df
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

try:
    from exchange.binance_client import BinanceClient
    client = BinanceClient()
except Exception as e:
    st.error(f"Binance Client Init Error: {e}")
    client = None

# --- UI Setup ---
st.set_page_config(page_title="Anything.ai Alpha Health", layout="wide", page_icon="🏥")
st.title("🛡️ Alpha Engine Health & Price Monitor")

# --- Row 1: Infrastructure Status ---
st.subheader("🌐 Infrastructure Status")
s_col1, s_col2, s_col3 = st.columns(3)

with s_col1:
    webhook_up = any(conn.laddr.port == 5000 for conn in psutil.net_connections() if conn.status == 'LISTEN')
    st.metric("Webhook (Port 5000)", "UP ✅" if webhook_up else "DOWN ❌")

with s_col2:
    try:
        orch_status = subprocess.check_output(['systemctl', 'is-active', 'trading_orchestrator']).decode().strip()
        orch_up = (orch_status == "active")
    except:
        orch_up = False
    st.metric("Orchestrator Engine", "ACTIVE ✅" if orch_up else "OFFLINE ❌")

with s_col3:
    STORAGE_PATH = os.path.join(PROJECT_ROOT, "storage/signals.jsonl")
    storage_ready = os.path.exists(STORAGE_PATH)
    st.metric("Storage System", "READY ✅" if storage_ready else "ERROR ❌")

st.divider()

# --- Row 2: Price substitution & Balance ---
st.subheader("📊 Market Data & Substitution (Mainnet vs Testnet)")
if client:
    try:
        mainnet_p = client.get_mainnet_mark_price("BTCUSDT")
        testnet_p = float(client.client.futures_symbol_ticker(symbol="BTCUSDT")['price'])
        health = client.get_account_health()

        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1: st.metric("Mainnet Price (Real)", f"${mainnet_p:,.2f}")
        with m_col2:
            diff = abs(mainnet_p - testnet_p)
            st.metric("Price Sync Status", "🟢 HEALTHY" if diff/mainnet_p < 0.005 else "🔴 DRIFT", delta=f"{diff:.2f} USD Diff")
        with m_col3: st.metric("Testnet Balance", f"${health['available_balance']:,.2f}")
    except:
        st.error("Live price sync failed. Check API connectivity.")
else:
    st.error("Client not initialized. Check /etc/tradingbot/env_vars")

st.divider()

# --- Row 3: Vitals & Optimized Logs ---
st.subheader("💓 System Vitals & Recent Logs")
v_col1, v_col2 = st.columns([1, 2])

with v_col1:
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    st.metric("CPU Usage", f"{cpu}%")
    st.metric("RAM Usage", f"{ram}%", delta=f"{ram-80}%" if ram > 80 else None, delta_color="inverse")

    try:
        hb = subprocess.check_output("journalctl -u trading_orchestrator -n 50 | grep 'Heartbeat' | tail -n 1", shell=True).decode()
        st.info(f"Latest Heartbeat: {hb.split('ip-172-31-26-202')[-1] if hb else 'N/A'}")
    except:
        st.warning("Heartbeat missing")

with v_col2:
    AUDIT_PATH = "/home/ubuntu/tradingview_webhook_bot/trading_audit_12h.csv"
    # Optimized Loading: Reading only last 10 lines
    df = get_optimized_logs(AUDIT_PATH, n=10)
    if not df.empty:
        st.dataframe(df, use_container_width=True)
    else:
        st.write("Audit logs loading...")

# Clean memory before sleeping
import gc
clear_memory()

time.sleep(30)
st.rerun()

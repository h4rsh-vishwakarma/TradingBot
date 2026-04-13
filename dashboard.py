import html
import streamlit as st
import pandas as pd
import psutil
import subprocess
import os, sys, gc, glob, json, time
import requests as _requests
from io import StringIO
from datetime import datetime, date, timedelta

try:
    import plotly.graph_objects as go
    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False

# -- paths ----------------------------------------------------------------------
PROJECT_ROOT   = "/home/ubuntu/tradingview_webhook_bot"
STRATEGIES_DIR = os.path.join(PROJECT_ROOT, "strategies")
REPORTS_DIR    = os.path.join(PROJECT_ROOT, "storage/reports")
TOURNAMENT_4H  = os.path.join(REPORTS_DIR,  "tournament_winners_4h.csv")
ALPHA_ALL_CSV  = os.path.join(REPORTS_DIR,  "alpha_backtest_results.csv")
ALPHA_VAL_CSV  = os.path.join(REPORTS_DIR,  "alpha_candidates.csv")
ALPHA_BEST_CSV = os.path.join(REPORTS_DIR,  "alpha_best_per_symbol.csv")
ALPHA_SHORTLIST_CSV = os.path.join(REPORTS_DIR, "alpha_shortlist.csv")
ALPHA_STATUS   = os.path.join(REPORTS_DIR,  "alpha_pipeline_status.json")
ALPHA_SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "storage/generated_alpha_scripts")
LEDGER_PATH    = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/ledger_state.json")
SIGNALS_PATH   = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/signals.jsonl")
ALERTS_PATH    = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/alerts.jsonl")
SETTINGS_PATH  = os.path.join(PROJECT_ROOT, "config/settings.json")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tradingview_webhook_bot"))

SYMBOLS_16 = ["FILUSDT","OPUSDT","LDOUSDT","UNIUSDT","NEARUSDT","INJUSDT",
               "SUIUSDT","ARBUSDT","AAVEUSDT","DOGEUSDT","APTUSDT","ATOMUSDT",
               "SOLUSDT","LINKUSDT","AVAXUSDT","DOTUSDT"]

# -- helpers --------------------------------------------------------------------
def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def read_jsonl(path, n=30):
    rows = []
    try:
        if not os.path.exists(path):
            return rows
        proc = subprocess.Popen(['tail', '-n', str(n * 4), path],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out, _ = proc.communicate(timeout=5)
        for line in out.decode(errors="ignore").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line.strip()))
                except:
                    pass
    except:
        pass
    return rows[-n:]

def is_process_running(name_fragment):
    """Check if a process is running by name fragment — reliable alternative to systemctl."""
    try:
        for p in psutil.process_iter(['cmdline', 'status']):
            try:
                cmd = " ".join(p.info.get('cmdline') or [])
                if name_fragment in cmd and p.info.get('status') != 'zombie':
                    return True
            except:
                pass
    except:
        pass
    return False

def is_port_listening(port):
    try:
        return any(c.laddr.port == port for c in psutil.net_connections()
                   if c.status == 'LISTEN')
    except:
        return False

TOURNAMENT_NUMERIC_COLS = [
    "Daily_ROI_%",
    "Gross_DD_%",
    "Net_DD_%",
    "Win_Rate_%",
    "Sharpe_Ratio",
    "OOS_Daily_ROI_%",
    "OOS_Gross_DD_%",
    "OOS_Sharpe",
    "Optimal_SL_%",
    "Optimal_TP_%",
    "Total_Trades",
]

def to_float(value, default=0.0):
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return default
        if isinstance(value, str):
            cleaned = value.strip().replace("%", "").replace(",", "")
            if not cleaned:
                return default
            return float(cleaned)
        return float(value)
    except:
        return default

def read_csv_safe(path):
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except:
        return pd.DataFrame()

def read_tournament_csv(path):
    df = read_csv_safe(path)
    if df.empty:
        return df
    for col in TOURNAMENT_NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].apply(lambda v: to_float(v, default=float("nan")))
    return df

def parse_position_meta(pos):
    raw_symbol = str(pos.get("symbol", "") or "")
    parts = raw_symbol.split(":")
    if len(parts) >= 3:
        asset = parts[1]
        strategy = ":".join(parts[2:]) or "Aggregate"
    elif len(parts) == 2:
        asset = parts[1]
        strategy = "Aggregate"
    else:
        asset = raw_symbol
        strategy = "Aggregate"
    return {"asset": asset or raw_symbol or "--", "strategy": strategy or "Aggregate"}

def compute_unrealized_pnl(qty, entry_price, mark_price):
    if not qty or not entry_price or not mark_price:
        return None
    return (mark_price - entry_price) * qty

# -- set_page_config MUST be first st call -------------------------------------
st.set_page_config(
    page_title="Trading Bot — Command Center",
    layout="wide",
    page_icon="?",
    initial_sidebar_state="expanded"
)

# -- session state --------------------------------------------------------------
if "page"          not in st.session_state: st.session_state.page          = "Home"
if "range"         not in st.session_state: st.session_state.range         = "Today"
if "bot"           not in st.session_state: st.session_state.bot           = "Binance"
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    * { font-family: 'Inter', sans-serif !important; }
    #MainMenu, footer, header, [data-testid="stToolbar"] { display: none !important; }
    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
        background: linear-gradient(135deg, #0a0e1a 0%, #0d1525 40%, #111d2e 100%) !important;
    }
    .block-container { padding-top: 0 !important; max-width: 100% !important; }
    [data-testid="stMainBlockContainer"] { padding: 0 !important; }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(2) > div {
        background: rgba(22, 27, 39, 0.85) !important;
        backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(56, 139, 253, 0.15) !important;
        border-radius: 24px !important;
        padding: 48px 40px 36px !important;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5), 0 0 120px rgba(31,111,235,0.06) !important;
    }
    [data-testid="stTextInput"] input {
        background: rgba(13, 17, 23, 0.8) !important;
        border: 1.5px solid rgba(48, 54, 61, 0.8) !important;
        border-radius: 12px !important;
        color: #e6edf3 !important;
        font-size: 15px !important;
        height: 50px !important;
        padding: 0 18px !important;
        transition: all 0.2s ease !important;
    }
    [data-testid="stTextInput"] input:focus {
        border-color: #388bfd !important;
        box-shadow: 0 0 0 3px rgba(56,139,253,0.15), 0 0 20px rgba(56,139,253,0.1) !important;
    }
    [data-testid="stTextInput"] input::placeholder { color: #484f58 !important; }
    [data-testid="stTextInput"] label { display: none !important; }
    [data-testid="stButton"] > button {
        background: linear-gradient(135deg, #1f6feb 0%, #388bfd 50%, #58a6ff 100%) !important;
        border: none !important;
        border-radius: 12px !important;
        color: #fff !important;
        font-size: 15px !important;
        font-weight: 600 !important;
        height: 50px !important;
        width: 100% !important;
        letter-spacing: 0.3px !important;
        margin-top: 8px !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 4px 15px rgba(31,111,235,0.3) !important;
    }
    [data-testid="stButton"] > button:hover {
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 25px rgba(31,111,235,0.4) !important;
    }
    [data-testid="stButton"] > button:active { transform: translateY(0) !important; }
    .pulse-dot {
        display: inline-block; width: 8px; height: 8px;
        background: #3fb950; border-radius: 50%;
        animation: pulse 2s infinite ease-in-out;
        box-shadow: 0 0 8px rgba(63,185,80,0.4);
    }
    @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.4;transform:scale(0.85)} }
    .glow-line {
        height: 2px; border-radius: 1px; margin: 28px 0 20px;
        background: linear-gradient(90deg, transparent, rgba(56,139,253,0.3), transparent);
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:14vh'></div>", unsafe_allow_html=True)
    _l, _mid, _r = st.columns([1, 1.4, 1])
    with _mid:
        st.markdown("""
        <div style="text-align:center;margin-bottom:32px">
          <div style="display:inline-flex;align-items:center;justify-content:center;
                      width:68px;height:68px;border-radius:20px;font-size:32px;
                      background:linear-gradient(135deg,#1f6feb,#388bfd);
                      box-shadow:0 8px 30px rgba(31,111,235,0.35);margin-bottom:18px">
            \U0001f4c8
          </div>
          <div style="font-size:26px;font-weight:800;color:#e6edf3;letter-spacing:-0.5px">
            TradingBot
          </div>
          <div style="font-size:13px;color:#6e7681;margin-top:6px;line-height:1.6;letter-spacing:0.2px">
            Automated Trading Command Center
          </div>
        </div>
        <div style="font-size:11px;font-weight:600;color:#8b949e;
                    text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">
            Password
        </div>
        """, unsafe_allow_html=True)
        _pw = st.text_input("pw", type="password", label_visibility="collapsed",
                            placeholder="Enter your password...", key="login_pw")
        _btn = st.button("\U0001f513  Unlock Dashboard", use_container_width=True)
        if _btn:
            _pw_file = os.path.join(PROJECT_ROOT, ".dashboard_password")
            try:
                with open(_pw_file) as _f:
                    correct_pw = _f.read().strip()
            except Exception:
                correct_pw = os.getenv("DASHBOARD_PASSWORD", "trading2026")
            if _pw == correct_pw:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.markdown(
                    "<div style='text-align:center;color:#f85149;font-size:13px;font-weight:500;"
                    "margin-top:12px;padding:10px 16px;background:rgba(248,81,73,0.08);"
                    "border:1px solid rgba(248,81,73,0.15);border-radius:10px'>"
                    "\u274c &nbsp;Incorrect password</div>", unsafe_allow_html=True)
        st.markdown('<div class="glow-line"></div>', unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;font-size:12px;color:#8b949e;
                    display:flex;align-items:center;justify-content:center;gap:8px">
          <span class="pulse-dot"></span>
          <span style="color:#3fb950;font-weight:500">System Online</span>
          <span style="color:#30363d">\u00b7</span>
          <span>Binance Futures</span>
          <span style="color:#30363d">\u00b7</span>
          <span>Paper Validation Active</span>
        </div>
        """, unsafe_allow_html=True)
    st.stop()




# -- non-blocking Binance client ------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_binance_client():
    import threading, queue
    q = queue.Queue()
    def _try():
        try:
            from exchange.binance_client import BinanceClient
            q.put(BinanceClient())
        except:
            q.put(None)
    threading.Thread(target=_try, daemon=True).start()
    try:
        return q.get(timeout=5)
    except:
        return None

@st.cache_resource(show_spinner=False)
def get_hl_client():
    import threading, queue
    q = queue.Queue()
    def _try():
        try:
            from exchange.hl_client import HyperliquidClient
            q.put(HyperliquidClient())
        except:
            q.put(None)
    threading.Thread(target=_try, daemon=True).start()
    try:
        return q.get(timeout=8)
    except:
        return None

@st.cache_resource(show_spinner=False)
def get_lighter_client():
    import threading, queue
    q = queue.Queue()
    def _try():
        try:
            from exchange.lighter_client import LighterClient
            q.put(LighterClient())
        except:
            q.put(None)
    threading.Thread(target=_try, daemon=True).start()
    try:
        return q.get(timeout=8)
    except:
        return None

client        = get_binance_client()
hl_client     = None
lighter_client = get_lighter_client()

# ------------------------------------------------------------------------------
#  DARK THEME CSS
# ------------------------------------------------------------------------------
st.markdown("""
<style>
/* ----------------------------------------------------
   DARK THEME — Clean, non-conflicting overrides only
   Theme colours set via .streamlit/config.toml
   ---------------------------------------------------- */

/* 1. Hide Streamlit chrome */
#MainMenu, footer, header { visibility: hidden; }

/* 2. Page background */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    background-color: #0d1117;
}

/* 3. Remove default Streamlit content padding (single rule) */
.block-container {
    padding: 0 !important;
    max-width: 100% !important;
}

/* 4. Add our own content padding below the nav */
[data-testid="stMainBlockContainer"] {
    padding: 0 18px 40px 18px;
}

/* 5. Sidebar */
[data-testid="stSidebar"] {
    background-color: #161b27;
    border-right: 1px solid #21262d;
    min-width: 175px;
    max-width: 175px;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] div,
[data-testid="stSidebar"] span {
    color: #8b949e;
}

/* 6. Nav pills container */
[data-testid="stPillsGroup"] {
    background-color: #161b27;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 4px 6px;
}
/* Unselected pill text colour (selected handled by config.toml primaryColor) */
[data-testid="stPillsGroup"] button p {
    color: #8b949e;
    font-size: 13px;
    font-weight: 500;
}
[data-testid="stPillsGroup"] button:hover p { color: #e6edf3; }

/* 7. Tabs */
[data-baseweb="tab-list"] {
    background-color: #161b27;
    border-radius: 8px;
    border: 1px solid #21262d;
    gap: 2px;
    padding: 3px;
}
[data-baseweb="tab"] {
    background-color: transparent;
    border-radius: 6px;
    color: #8b949e;
    font-size: 13px;
}
[data-baseweb="tab"][aria-selected="true"] {
    background-color: #1f6feb;
    color: #fff;
}

/* 8. DataFrames */
[data-testid="stDataFrameContainer"] {
    background-color: #1c2128;
    border: 1px solid #30363d;
    border-radius: 10px;
}

/* 9. Expander */
[data-testid="stExpander"] {
    background-color: #1c2128;
    border: 1px solid #30363d;
    border-radius: 10px;
}

/* 10. Alert/info boxes */
[data-testid="stAlert"] {
    background-color: #1c2128;
    border: 1px solid #30363d;
    border-radius: 8px;
    color: #8b949e;
}

/* -- Custom layout components -- */
.ticker-bar {
    background: #161b27;
    border-bottom: 1px solid #21262d;
    padding: 8px 18px;
    font-size: 12.5px;
    font-weight: 600;
    display: flex;
    gap: 18px;
    align-items: center;
    flex-wrap: nowrap;
    overflow: hidden;
}
.ticker-bar span { white-space: nowrap; color: #8b949e; }
.tv  { color: #3fb950; }
.td  { color: #f85149; }
.ticker-right { margin-left: auto; color: #58a6ff; font-size: 11.5px; }

.info-bar {
    background: #0d1117;
    border-bottom: 1px solid #21262d;
    padding: 5px 18px;
    font-size: 12px;
    display: flex;
    gap: 18px;
    align-items: center;
    flex-wrap: wrap;
}
.ib-key  { color: #58a6ff; font-weight: 600; margin-right: 3px; }
.ib-val  { color: #3fb950; }
.ib-warn { color: #f85149; }

.sec-title {
    font-size: 15px;
    font-weight: 700;
    color: #e6edf3;
    margin: 14px 0 10px 0;
    padding-bottom: 7px;
    border-bottom: 2px solid #21262d;
    display: flex;
    align-items: center;
    gap: 8px;
}

.dk-card {
    background: #1c2128;
    border: 1px solid #30363d;
    border-radius: 12px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
    height: 100%;
}
.dk-card-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; }
.dk-card-label  { font-size: 11.5px; color: #8b949e; font-weight: 500; margin-bottom: 6px; text-transform: uppercase; letter-spacing: .5px; }
.dk-card-value  { font-size: 24px; font-weight: 800; line-height: 1.1; margin-bottom: 5px; }
.dk-card-sub    { font-size: 11px; color: #6e7681; line-height: 1.5; }
.dk-card-icon   { position: absolute; top: 14px; right: 14px; font-size: 20px; opacity: .35; }

.chart-panel  { background: #1c2128; border: 1px solid #30363d; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
.chart-title  { font-size: 13.5px; font-weight: 700; color: #e6edf3; margin-bottom: 10px; }

.badge-bull    { background: #0d4429; color: #3fb950; padding: 3px 10px; border-radius: 20px; font-size: 11.5px; font-weight: 600; border: 1px solid #3fb950; }
.badge-bear    { background: #3d1a1a; color: #f85149; padding: 3px 10px; border-radius: 20px; font-size: 11.5px; font-weight: 600; border: 1px solid #f85149; }
.badge-neutral { background: #1c2128; color: #8b949e; padding: 3px 10px; border-radius: 20px; font-size: 11.5px; font-weight: 600; border: 1px solid #30363d; }
.badge-active  { background: #0d4429; color: #3fb950; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.badge-warn    { background: #3d2b00; color: #d29922; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }

.tbl-wrap          { background: #1c2128; border-radius: 10px; border: 1px solid #30363d; overflow: hidden; margin-bottom: 12px; }
.tbl-wrap table    { width: 100%; border-collapse: collapse; }
.tbl-wrap th       { background: #161b27; color: #8b949e; font-size: 11.5px; font-weight: 600; padding: 9px 13px; text-align: left; border-bottom: 1px solid #30363d; }
.tbl-wrap td       { color: #e6edf3; font-size: 13px; padding: 9px 13px; border-bottom: 1px solid #21262d; }
.tbl-wrap tr:last-child td { border-bottom: none; }
.tbl-wrap tr:hover td      { background: #21262d; }

.logbox {
    background: #0d1117;
    border-radius: 8px;
    border: 1px solid #30363d;
    padding: 12px 15px;
    max-height: 300px;
    overflow-y: auto;
    font-family: 'Courier New', monospace;
    font-size: 11.5px;
    line-height: 1.7;
}
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
#  DATA LOAD
# ------------------------------------------------------------------------------
ledger    = load_json(LEDGER_PATH)
positions = ledger.get("positions", {})
th        = ledger.get("trade_history", [])
settings  = load_json(SETTINGS_PATH)
risk      = settings.get("risk", {})
trading   = settings.get("trading", {})

# Service checks via psutil (reliable — no systemctl needed)
webhook_up  = is_port_listening(5000)
orch_up     = is_process_running("orchestrator.py")
hl_up       = is_process_running("hl_mirror.py")
t4h_ready   = os.path.exists(TOURNAMENT_4H)
lighter_up  = lighter_client is not None and getattr(lighter_client, "is_ready", False)

# Position data
open_pos   = [p for p in positions.values() if abs(p.get("quantity", 0)) > 0]
sl_pct     = float(risk.get("stop_loss_pct",    os.getenv("STOP_LOSS_PCT",    2.0)))
tp_pct     = float(risk.get("take_profit_pct",  os.getenv("TAKE_PROFIT_PCT",  6.0)))
today_str  = date.today().isoformat()
week_str   = (date.today() - timedelta(days=7)).isoformat()
month_str  = (date.today() - timedelta(days=30)).isoformat()
RANGES     = {"Today": today_str, "This Week": week_str, "This Month": month_str, "All Time": "2000"}

def pnl_since(since):
    return sum(t.get("pnl", 0) for t in th if t.get("timestamp", "") >= since)

alltime_pnl  = sum(t.get("pnl", 0) for t in th)
today_pnl    = pnl_since(today_str)
open_unr_pnl = 0.0
wins         = sum(1 for t in th if t.get("pnl", 0) > 0)
win_rate     = (wins / len(th) * 100) if th else 0

# Live prices — fetch from Binance PUBLIC API (no auth, bypasses testnet issues)
@st.cache_data(ttl=30, show_spinner=False)
def fetch_public_prices(extra_symbols=None):
    _base_syms = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","LINKUSDT","DOGEUSDT","AVAXUSDT"]
    _syms = list(dict.fromkeys(_base_syms + [str(s).upper() for s in (extra_symbols or []) if s]))
    try:
        import requests as _req
        r = _req.get("https://api.binance.com/api/v3/ticker/price", timeout=5)
        if r.status_code == 200:
            _data = {item["symbol"]: float(item["price"]) for item in r.json()}
            return {s: _data.get(s) for s in _syms}
    except:
        pass
    # fallback: try via testnet client
    _out = {}
    for s in _syms:
        try:
            _out[s] = client.get_mainnet_mark_price(s) if client else None
        except:
            _out[s] = None
    return _out

open_assets = sorted({parse_position_meta(p)["asset"] for p in open_pos if parse_position_meta(p)["asset"]})
prices = fetch_public_prices(tuple(open_assets))

open_pos_enriched = []
for p in open_pos:
    _row = dict(p)
    _meta = parse_position_meta(_row)
    _qty = to_float(_row.get("quantity", 0))
    _entry = to_float(_row.get("avg_price", 0))
    _mark = prices.get(_meta["asset"])
    _row["_asset"] = _meta["asset"]
    _row["_strategy"] = _meta["strategy"]
    _row["_mark_price"] = _mark
    _row["_unrealized_pnl"] = compute_unrealized_pnl(_qty, _entry, _mark)
    _row["_day_pnl"] = (
        to_float(_row.get("daily_realized_pnl", 0))
        if str(_row.get("last_update_date", "")) == today_str else 0.0
    )
    open_pos_enriched.append(_row)

open_pos = open_pos_enriched
open_unr_pnl = sum((p.get("_unrealized_pnl") or 0.0) for p in open_pos)
open_assets_label = ", ".join(open_assets[:4]) if open_assets else "No open assets"
if len(open_assets) > 4:
    open_assets_label += ", ..."

def fp(sym, d=2):
    p = prices.get(sym)
    return f"${p:,.{d}f}" if p else "--"

# HyperLiquid balance
hl_balance = 0.0
hl_wallet  = os.getenv("HL_WALLET_ADDRESS", "0xd31b417C007609fd7babc94ED71eB26e5f6397Ef")
try:
    if hl_client and getattr(hl_client, 'info', None) and hasattr(hl_client, 'get_balance'):
        hl_balance = hl_client.get_balance() or 0.0
except:
    pass

# ------------------------------------------------------------------------------
#  SIDEBAR — status panel only (nav moved to top bar)
# ------------------------------------------------------------------------------
def sdot(ok):
    c = "#3fb950" if ok else "#f85149"
    return f'<span style="color:{c};font-size:9px">?</span>'

with st.sidebar:
    st.markdown(f"""
    <div style='padding:16px 14px 8px 14px'>
      <div style='font-size:17px;font-weight:900;color:#58a6ff;margin-bottom:2px'>? TradingBot</div>
      <div style='font-size:10px;color:#6e7681'>Command Center</div>
    </div>
    <hr style='border-color:#21262d;margin:0 0 10px 0'/>
    <div style='padding:6px 14px;font-size:11.5px;line-height:2.4'>
      <div>{sdot(webhook_up)} <span style='color:#8b949e'>Webhook :5000</span></div>
      <div>{sdot(orch_up)} <span style='color:#8b949e'>Orchestrator</span></div>
      <div>{sdot(hl_up)} <span style='color:#8b949e'>HL Mirror</span></div>
      <div>{sdot(lighter_up)} <span style='color:#8b949e'>Lighter DEX</span></div>
      <div>{sdot(t4h_ready)} <span style='color:#8b949e'>4H Data Ready</span></div>
    </div>
    <hr style='border-color:#21262d;margin:6px 0'/>
    <div style='padding:6px 14px;font-size:11px;color:#6e7681;line-height:2'>
      <div>Mode: <b style='color:#58a6ff'>4H Futures</b></div>
      <div>SL: <b style='color:#f85149'>{sl_pct:.0f}%</b> &nbsp; TP: <b style='color:#3fb950'>{tp_pct:.0f}%</b></div>
      <div>Network: <b style='color:#d29922'>TESTNET</b></div>
      <div>Page: <b style='color:#e6edf3'>{st.session_state.page}</b></div>
    </div>
    <hr style='border-color:#21262d;margin:6px 0'/>
    <div style='padding:6px 14px;font-size:10.5px;color:#6e7681'>
      Open Positions: <b style='color:#e6edf3'>{len(open_pos)}</b><br>
      Win Rate: <b style='color:#{"3fb950" if win_rate>=50 else "f85149"}'>{win_rate:.1f}%</b><br>
      All-time PnL: <b style='color:#{"3fb950" if alltime_pnl>=0 else "f85149"}'>${alltime_pnl:+,.2f}</b>
    </div>
    <hr style='border-color:#21262d;margin:6px 0'/>
    """, unsafe_allow_html=True)
    if st.button("Logout", use_container_width=True, key="logout_btn"):
        st.session_state.authenticated = False
        st.rerun()


# ------------------------------------------------------------------------------
#  TICKER BAR (always shown)
# ------------------------------------------------------------------------------
st.markdown(f"""
<div class="ticker-bar">
  <span>BTC&nbsp;<span class="tv">{fp("BTCUSDT",0)}</span></span>
  <span>ETH&nbsp;<span class="tv">{fp("ETHUSDT",2)}</span></span>
  <span>SOL&nbsp;<span class="tv">{fp("SOLUSDT",2)}</span></span>
  <span>BNB&nbsp;<span class="tv">{fp("BNBUSDT",2)}</span></span>
  <span>LINK&nbsp;<span class="tv">{fp("LINKUSDT",2)}</span></span>
  <span>DOGE&nbsp;<span class="tv">{fp("DOGEUSDT",4)}</span></span>
  <span>AVAX&nbsp;<span class="tv">{fp("AVAXUSDT",2)}</span></span>
  <span class="ticker-right">? 4H · SL {sl_pct:.0f}% / TP {tp_pct:.0f}% · TESTNET · {datetime.now().strftime("%d %b %Y  %H:%M:%S")}</span>
</div>
<div class="info-bar">
  <span><span class="ib-key">BINANCE BOT:</span>
    <span class="ib-val">{len(open_pos)} Open</span></span>
  <span><span class="ib-key">TOTAL PNL:</span>
    <span class="{"ib-val" if alltime_pnl>=0 else "ib-warn"}">${alltime_pnl:+,.4f}</span></span>
  <span><span class="ib-key">HL MIRROR:</span>
    <span class="{"ib-val" if hl_up else "ib-warn"}">{"? ACTIVE" if hl_up else "? OFFLINE"}</span></span>
  <span><span class="ib-key">ORCHESTRATOR:</span>
    <span class="{"ib-val" if orch_up else "ib-warn"}">{"? RUNNING" if orch_up else "? OFFLINE"}</span></span>
  <span><span class="ib-key">WIN RATE:</span>
    <span class="ib-val">{win_rate:.1f}% ({wins}/{len(th)})</span></span>
</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
#  TOP NAVIGATION — using st.pills (no CSS conflicts)
# ------------------------------------------------------------------------------
_PAGE_MAP = {
    "Home":          "Home",
    "?  Kill Switch":   "Kill Switch",
    "Order Manager": "Order Manager",
    "Alerts":        "Alerts",
    "Order Status":  "Order Status",
    "Signals":       "Signals",
    "Backtest":      "Backtest",
    "Lighter":       "Lighter",
}
_LABEL_MAP  = {v: k for k, v in _PAGE_MAP.items()}
_cur_label  = _LABEL_MAP.get(st.session_state.page, "Home")
_pill_sel   = st.pills("nav", list(_PAGE_MAP.keys()),
                        default=_cur_label, label_visibility="collapsed")
if _pill_sel and _PAGE_MAP.get(_pill_sel) != st.session_state.page:
    st.session_state.page = _PAGE_MAP[_pill_sel]
    st.rerun()

st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
#  HOME
# ------------------------------------------------------------------------------
if st.session_state.page == "Home":

    # -- bot selector + range pills -----------------------------------------
    bot_col, range_col = st.columns([2, 5])
    with bot_col:
        bot_sel = st.radio("Select Bot", ["Binance Bot", "HyperLiquid Bot"],
                           horizontal=True, label_visibility="collapsed",
                           key="bot_radio")
        st.session_state.bot = "Binance" if "Binance" in bot_sel else "HyperLiquid"

    with range_col:
        rcols = st.columns(4)
        for i, lbl in enumerate(["Today", "This Week", "This Month", "All Time"]):
            active_cls = "rpill-active" if st.session_state.range == lbl else ""
            if rcols[i].button(lbl, key=f"rng_{lbl}", use_container_width=True):
                st.session_state.range = lbl
                st.rerun()

    since_date = RANGES.get(st.session_state.range, "2000")
    range_pnl  = pnl_since(since_date)

    # -- BINANCE BOT ---------------------------------------------------------
    if st.session_state.bot == "Binance":

        # 4 metric cards
        c1, c2, c3, c4 = st.columns(4)

        with c1:
            total_invested = sum(
                abs(p.get("quantity", 0)) * p.get("avg_price", 0) for p in open_pos)
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#1f6feb,#388bfd)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Capital Deployed</div>
              <div class="dk-card-value" style="color:#58a6ff">${total_invested:,.2f}</div>
              <div class="dk-card-sub">{len(open_pos)} active position(s)<br>
                Binance Futures Testnet</div>
            </div>""", unsafe_allow_html=True)

        with c2:
            c2_col = "#3fb950" if range_pnl >= 0 else "#f85149"
            at_col = "#3fb950" if alltime_pnl >= 0 else "#f85149"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Realised PnL ({st.session_state.range})</div>
              <div class="dk-card-value" style="color:{c2_col}">${range_pnl:+,.4f}</div>
              <div class="dk-card-sub">All-time: <span style="color:{at_col};font-weight:600">${alltime_pnl:+,.4f}</span><br>
                {wins} wins / {len(th)} closed trades</div>
            </div>""", unsafe_allow_html=True)

        with c3:
            unr_col = "#3fb950" if open_unr_pnl >= 0 else "#f85149"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#d29922,#e3b341)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Open Position PnL</div>
              <div class="dk-card-value" style="color:{unr_col}">${open_unr_pnl:+,.4f}</div>
              <div class="dk-card-sub">{len(open_pos)} positions open<br>
                {open_assets_label}</div>
            </div>""", unsafe_allow_html=True)

        with c4:
            wr_col = "#3fb950" if win_rate >= 50 else "#f85149"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
              <div class="dk-card-icon">?</div>
              <div class="dk-card-label">Win Rate</div>
              <div class="dk-card-value" style="color:{wr_col}">{win_rate:.1f}%</div>
              <div class="dk-card-sub">{wins} wins / {len(th) - wins} losses<br>
                <span class="badge-active">? Orchestrator ACTIVE</span></div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # -- Charts --------------------------------------------------------
        ch1, ch2 = st.columns([3, 2])

        with ch1:
            st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
            st.markdown('<div class="chart-title">Cumulative PnL</div>', unsafe_allow_html=True)
            if HAS_PLOTLY and th:
                df_h = pd.DataFrame(th)
                df_h['ts'] = pd.to_datetime(df_h['timestamp'], errors='coerce')
                df_h = df_h.dropna(subset=['ts']).sort_values('ts')
                if since_date != "2000":
                    df_h = df_h[df_h['ts'] >= pd.Timestamp(since_date)]
                df_h['cum'] = df_h['pnl'].cumsum()
                if not df_h.empty:
                    last_val = df_h['cum'].iloc[-1]
                    lc = '#3fb950' if last_val >= 0 else '#f85149'
                    fc = 'rgba(63,185,80,.12)' if last_val >= 0 else 'rgba(248,81,73,.12)'
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df_h['ts'], y=df_h['cum'], mode='lines',
                        line=dict(color=lc, width=2.5),
                        fill='tozeroy', fillcolor=fc,
                        hovertemplate='%{x|%d %b %H:%M}<br>PnL: $%{y:+.4f}<extra></extra>',
                    ))
                    fig.add_hline(y=0, line_color='#30363d', line_width=1)
                    fig.update_layout(
                        height=220, margin=dict(l=0, r=0, t=0, b=0),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        xaxis=dict(gridcolor='#21262d', tickformat='%d %b',
                                   tickfont=dict(size=10, color='#6e7681'), showgrid=True,
                                   linecolor='#30363d'),
                        yaxis=dict(gridcolor='#21262d', tickprefix='$',
                                   tickfont=dict(size=10, color='#6e7681'),
                                   linecolor='#30363d'),
                        showlegend=False,
                        font=dict(color='#8b949e'),
                    )
                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                else:
                    st.markdown('<div style="text-align:center;color:#6e7681;padding:60px 0;font-size:13px">No data for selected range</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="text-align:center;color:#6e7681;padding:60px 0;font-size:13px">No trade history available</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        with ch2:
            st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
            st.markdown('<div class="chart-title">Open Positions by Symbol</div>', unsafe_allow_html=True)
            if HAS_PLOTLY and open_pos:
                sym_data = {}
                for p in open_pos:
                    sym = p.get("symbol", "").replace("binance:", "").split(":")[0]
                    val = abs(p.get("quantity", 0)) * p.get("avg_price", 0)
                    sym_data[sym] = sym_data.get(sym, 0) + val
                colors = ['#1f6feb','#388bfd','#58a6ff','#79c0ff','#a5d6ff',
                          '#3fb950','#56d364','#7ee787','#bc8cff','#d2a8ff']
                fig2 = go.Figure(go.Pie(
                    labels=list(sym_data.keys()),
                    values=[round(v, 2) for v in sym_data.values()],
                    hole=0.55,
                    marker_colors=colors[:len(sym_data)],
                    textinfo='label+percent',
                    textfont_size=10,
                    textfont_color='#e6edf3',
                ))
                fig2.update_layout(
                    height=220, margin=dict(l=0, r=0, t=0, b=0),
                    paper_bgcolor='rgba(0,0,0,0)', showlegend=False,
                    annotations=[dict(text=f'<b style="color:#e6edf3">{len(open_pos)}<br>Open</b>',
                                      x=0.5, y=0.5, font_size=12,
                                      showarrow=False, font_color='#e6edf3')]
                )
                st.plotly_chart(fig2, use_container_width=True, config={'displayModeBar': False})
            else:
                st.markdown('<div style="text-align:center;color:#6e7681;padding:60px 0;font-size:13px">No open positions</div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

        # -- Open Positions table ------------------------------------------
        st.markdown('<div class="sec-title">Open Positions</div>', unsafe_allow_html=True)
        if open_pos:
            rows_html = ""
            for p in open_pos:
                asset = html.escape(str(p.get("_asset", "--")))
                strategy = html.escape(str(p.get("_strategy", "Aggregate")))
                qty  = p.get("quantity", 0)
                ep   = p.get("avg_price", 0)
                upnl = p.get("_unrealized_pnl")
                dpnl = p.get("_day_pnl", 0)
                side = "LONG" if qty > 0 else "SHORT"
                tp_p = ep * (1 + tp_pct / 100) if qty > 0 else ep * (1 - tp_pct / 100)
                sl_p = ep * (1 - sl_pct / 100) if qty > 0 else ep * (1 + sl_pct / 100)
                upnl_c = "#3fb950" if (upnl or 0) >= 0 else "#f85149"
                upnl_v = f"${upnl:+.4f}" if upnl is not None else "--"
                rows_html += f"""
                <tr>
                  <td style="font-weight:600;color:#58a6ff">{asset}</td>
                  <td style="color:#e6edf3;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{strategy}</td>
                  <td>{side}</td>
                  <td style="color:#e6edf3">{abs(qty):.4f}</td>
                  <td style="color:#e6edf3">${ep:,.4f}</td>
                  <td style="color:#3fb950">${tp_p:,.4f}</td>
                  <td style="color:#f85149">${sl_p:,.4f}</td>
                  <td style="color:{upnl_c};font-weight:600">{upnl_v}</td>
                  <td style="color:{'#3fb950' if dpnl >= 0 else '#f85149'}">${dpnl:+.4f}</td>
                  <td style="color:#6e7681;font-size:11px">{p.get("last_update_date","")}</td>
                </tr>"""
            st.markdown(f"""
            <div class="tbl-wrap">
            <table>
              <thead><tr>
                <th>Asset</th><th>Strategy</th><th>Side</th><th>Qty</th><th>Entry</th>
                <th>TP Price</th><th>SL Price</th><th>Unrealized PnL</th>
                <th>Day's PnL</th><th>Updated</th>
              </tr></thead>
              <tbody>{rows_html}</tbody>
            </table></div>""", unsafe_allow_html=True)
        else:
            st.info("No open positions.")

    # -- HYPERLIQUID BOT ------------------------------------------------------
    else:
        hl_c1, hl_c2, hl_c3 = st.columns(3)
        with hl_c1:
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">HL Balance (USDC)</div>
              <div class="dk-card-value" style="color:#bc8cff">${hl_balance:,.4f}</div>
              <div class="dk-card-sub">HyperLiquid Testnet</div>
            </div>""", unsafe_allow_html=True)
        with hl_c2:
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Mirror Bot Status</div>
              <div class="dk-card-value" style="color:{'#3fb950' if hl_up else '#f85149'}">{'ACTIVE' if hl_up else 'OFFLINE'}</div>
              <div class="dk-card-sub">Running since 2026-03-21<br>Lead trader mirror mode</div>
            </div>""", unsafe_allow_html=True)
        with hl_c3:
            short_wallet = hl_wallet[:10] + "..." + hl_wallet[-6:] if hl_wallet else "—"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#58a6ff,#79c0ff)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Wallet Address</div>
              <div class="dk-card-value" style="color:#58a6ff;font-size:16px">{short_wallet}</div>
              <div class="dk-card-sub">Network: Testnet<br>
                Trader: 0x0e61...80dd</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style='background:#1c2128;border:1px solid #30363d;border-radius:10px;padding:18px 20px;color:#8b949e;font-size:13px'>
          <b style='color:#bc8cff'>HyperLiquid Mirror Bot</b> is actively mirroring lead trader positions.
          Trade data will appear here as positions are opened and closed on HyperLiquid testnet.<br><br>
          <b style='color:#58a6ff'>Lead Trader:</b> 0x0e61a8fb14f6ac999646212d30b2192cd02080dd &nbsp;|&nbsp;
          <b style='color:#58a6ff'>Poll Interval:</b> 5s &nbsp;|&nbsp;
          <b style='color:#58a6ff'>Mode:</b> Testnet
        </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
#  KILL SWITCH
# ------------------------------------------------------------------------------
elif st.session_state.page == "Kill Switch":

    st.markdown('<div class="sec-title">? Kill Switch — Safety Controls</div>', unsafe_allow_html=True)

    dd_lim     = float(risk.get("max_drawdown_limit", os.getenv("CB_DAILY_LOSS_PCT", 10.0)))
    today_loss = abs(today_pnl) if today_pnl < 0 else 0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        lc = "#f85149" if today_loss > 0 else "#3fb950"
        st.markdown(f"""
        <div class="dk-card">
          <div class="dk-card-accent" style="background:linear-gradient(90deg,#f85149,#ff6b6b)"></div>
          <div class="dk-card-label">Entry Loss Today</div>
          <div class="dk-card-value" style="color:{lc}">${today_loss:,.4f}</div>
          <div class="dk-card-sub">Realized losses today</div>
        </div>""", unsafe_allow_html=True)
    with k2:
        st.markdown(f"""
        <div class="dk-card">
          <div class="dk-card-accent" style="background:linear-gradient(90deg,#d29922,#e3b341)"></div>
          <div class="dk-card-label">Daily Loss Limit</div>
          <div class="dk-card-value" style="color:#d29922">{dd_lim:.1f}%</div>
          <div class="dk-card-sub">Circuit breaker threshold</div>
        </div>""", unsafe_allow_html=True)
    with k3:
        st.markdown(f"""
        <div class="dk-card">
          <div class="dk-card-accent" style="background:linear-gradient(90deg,#f85149,#ff6b6b)"></div>
          <div class="dk-card-label">Stop Loss</div>
          <div class="dk-card-value" style="color:#f85149">{sl_pct:.1f}%</div>
          <div class="dk-card-sub">Per trade · 4H candle</div>
        </div>""", unsafe_allow_html=True)
    with k4:
        st.markdown(f"""
        <div class="dk-card">
          <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
          <div class="dk-card-label">Take Profit</div>
          <div class="dk-card-value" style="color:#3fb950">{tp_pct:.1f}%</div>
          <div class="dk-card-sub">R:R = 1:{int(tp_pct / sl_pct) if sl_pct else 3}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # System status table
    st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
    st.markdown('<div class="chart-title">System Safety Status</div>', unsafe_allow_html=True)
    raw_rows = [
        ("Webhook Server",      f"{'ACTIVE :5000' if webhook_up else 'DOWN'}"),
        ("Orchestrator",        f"{'RUNNING' if orch_up else 'OFFLINE'}"),
        ("HyperLiquid Mirror",  f"{'ACTIVE' if hl_up else 'OFFLINE'}"),
        ("Price Sanity Check",  "? ON — 80%+ match required"),
        ("Max Positions",       str(risk.get("max_positions", os.getenv("MAX_OPEN_POSITIONS", 16)))),
        ("Position Size",       f"{risk.get('position_size_value', os.getenv('EQUITY_PCT_PER_TRADE', 10))}% of equity"),
        ("Leverage",            str(trading.get("leverage", os.getenv("TRADE_LEVERAGE", 1)))),
        ("Signal Expiry",       f"{settings.get('strategies', {}).get('signal_expiry_seconds', 300)}s"),
        ("Fee Drag (4H mode)",  "~0.04%/day (was 0.87% on 15m)"),
        ("Trade Mode",          "TESTNET — paper trading"),
    ]
    st.dataframe(
        pd.DataFrame(raw_rows, columns=["Parameter", "Value"]),
        use_container_width=True, hide_index=True
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # -- Bot Control Buttons ------------------------------------------------
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sec-title">?Bot Controls</div>', unsafe_allow_html=True)

    try:
        _bot_resp   = _requests.get("http://127.0.0.1:5000/bot/status", timeout=3).json()
        _orch_run   = _bot_resp.get("orchestrator") == "running"
        _real_trades = _bot_resp.get("allow_real_trades", False)
    except Exception:
        _orch_run    = orch_up   # fallback to psutil check
        _real_trades = os.getenv("ALLOW_REAL_TRADES", "false").lower() == "true"

    _status_color = "#3fb950" if _orch_run else "#f85149"
    _status_label = "? RUNNING" if _orch_run else "? STOPPED"
    _trades_label = "LIVE TRADES ON" if _real_trades else "Paper / Testnet"
    _trades_color = "#f85149" if _real_trades else "#d29922"

    st.markdown(f"""
    <div class="dk-card" style="margin-bottom:14px">
      <div class="dk-card-label">Orchestrator Status</div>
      <span style="color:{_status_color};font-weight:700;font-size:15px">{_status_label}</span>
      &nbsp;&nbsp;<span style="color:{_trades_color};font-size:12px;font-weight:600">{_trades_label}</span>
    </div>""", unsafe_allow_html=True)

    _bc1, _bc2, _bc3 = st.columns(3)
    with _bc1:
        if st.button("Start Bot", use_container_width=True,
                     disabled=_orch_run, key="ks_start"):
            try:
                _r = _requests.post("http://127.0.0.1:5000/bot/start",
                                    json={}, timeout=5)
                if _r.status_code == 200:
                    st.success("? Bot started")
                    st.rerun()
                else:
                    st.error(f"Error: {_r.text[:100]}")
            except Exception as _e:
                st.error(f"Request failed: {_e}")
    with _bc2:
        if st.button("Stop Bot", use_container_width=True,
                     disabled=not _orch_run, key="ks_stop"):
            try:
                _r = _requests.post("http://127.0.0.1:5000/bot/stop",
                                    json={}, timeout=5)
                if _r.status_code == 200:
                    st.success("? Bot stopped")
                    st.rerun()
                else:
                    st.error(f"Error: {_r.text[:100]}")
            except Exception as _e:
                st.error(f"Request failed: {_e}")
    with _bc3:
        if st.button("Emergency Kill", use_container_width=True,
                     type="primary", key="ks_emergency"):
            try:
                _r = _requests.post("http://127.0.0.1:5000/bot/emergency",
                                    json={}, timeout=15)
                if _r.status_code == 200:
                    _d = _r.json()
                    st.error(f"Emergency kill executed — {_d.get('positions_closed', 0)} positions closed")
                    st.rerun()
                else:
                    st.error(f"Error: {_r.text[:100]}")
            except Exception as _e:
                st.error(f"Request failed: {_e}")

    st.markdown("""
    <div style="font-size:11px;color:#6e7681;margin-top:8px;padding:8px 12px;
                background:#1c2128;border-radius:8px;border:1px solid #30363d">
      <b>Start Bot</b> — restarts the trading_orchestrator systemd service.<br>
      <b>Stop Bot</b> — gracefully stops new signal processing (open trades remain).<br>
      <b>Emergency Kill</b> — closes ALL open positions on Binance then stops the bot.
    </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
#  ORDER MANAGER
# ------------------------------------------------------------------------------
elif st.session_state.page == "Order Manager":

    st.markdown('<div class="sec-title">Order Manager</div>', unsafe_allow_html=True)
    tab1, tab2 = st.tabs(["Open Positions", "Order Book"])

    with tab1:
        if open_pos:
            rows = []
            for p in open_pos:
                qty = p.get("quantity", 0)
                ep  = p.get("avg_price", 0)
                tp_p = ep * (1 + tp_pct / 100) if qty > 0 else ep * (1 - tp_pct / 100)
                sl_p = ep * (1 - sl_pct / 100) if qty > 0 else ep * (1 + sl_pct / 100)
                rows.append({
                    "Asset":    p.get("_asset", "--"),
                    "Strategy": p.get("_strategy", "Aggregate"),
                    "Side":     "LONG" if qty > 0 else "SHORT",
                    "Qty":      f"{abs(qty):.4f}",
                    "Entry":    f"${ep:,.4f}",
                    "TP":       f"${tp_p:,.4f}",
                    "SL":       f"${sl_p:,.4f}",
                    "Unrealized PnL": (
                        f"${p.get('_unrealized_pnl', 0):+.4f}" if p.get("_unrealized_pnl") is not None else "--"
                    ),
                    "Day's PnL": f"${p.get('_day_pnl', 0):+.4f}",
                    "Updated":  str(p.get("last_update_date", "")),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No open positions.")

    with tab2:
        df_hist = pd.DataFrame(th[-20:] if th else [])
        if not df_hist.empty:
            df_hist = df_hist.copy()
            df_hist['timestamp']  = df_hist['timestamp'].str[:19].str.replace("T", " ")
            df_hist['symbol']     = df_hist['symbol'].str.replace("binance:", "")
            df_hist['pnl']        = df_hist['pnl'].apply(lambda x: f"${float(x):+.4f}")
            df_hist['exit_price'] = df_hist['exit_price'].apply(lambda x: f"${float(x):,.4f}")
            st.dataframe(df_hist[['timestamp', 'symbol', 'pnl', 'exit_price']].rename(
                columns={'timestamp': 'Time', 'symbol': 'Symbol',
                         'pnl': 'PnL', 'exit_price': 'Exit Price'}),
                use_container_width=True, hide_index=True)
        else:
            st.info("No order history yet.")


# ------------------------------------------------------------------------------
#  ALERTS
# ------------------------------------------------------------------------------
elif st.session_state.page == "Alerts":

    st.markdown('<div class="sec-title">Alerts & System Logs</div>', unsafe_allow_html=True)

    lines_shown = False

    # Try alerts.jsonl first
    alert_rows = read_jsonl(ALERTS_PATH, n=40)
    if alert_rows:
        lines_shown = True
        html_parts = []
        for a in reversed(alert_rows[-30:]):
            if not isinstance(a, dict):
                continue
            msg   = str(a.get("message", a.get("text", str(a))))
            level = str(a.get("level", "INFO")).upper()
            ts    = str(a.get("timestamp", a.get("time", "")))[:19].replace("T", " ")
            c = ("#f85149" if "ERROR" in level or "FAIL" in msg.upper()
                 else "#d29922" if "WARN" in level
                 else "#3fb950" if any(x in msg.upper() for x in ["FILL","ORDER","ENTRY","EXIT","BUY","SELL"])
                 else "#8b949e")
            msg_esc = msg.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            html_parts.append(
                f'<div style="color:{c}"><span style="color:#6e7681;margin-right:8px">{ts}</span>{msg_esc}</div>')
        st.markdown('<div class="logbox">' + "".join(html_parts) + '</div>', unsafe_allow_html=True)

    # Try journalctl
    try:
        raw = subprocess.check_output(
            "journalctl -u trading_orchestrator -n 40 --no-pager --output=short",
            shell=True, timeout=5, stderr=subprocess.DEVNULL).decode(errors="ignore")
        if raw.strip():
            lines_shown = True
            st.markdown('<div class="chart-title" style="margin-top:14px">Orchestrator Log</div>', unsafe_allow_html=True)
            html_parts = []
            for ln in raw.strip().splitlines()[-25:]:
                l = ln.strip()
                if not l:
                    continue
                c = ("#f85149" if "ERROR" in l or "FAIL" in l
                     else "#d29922" if "WARN" in l
                     else "#3fb950" if any(x in l for x in ["FILL", "filled", "entry", "exit", "order", "Reconciler"])
                     else "#6e7681" if "Heartbeat" in l
                     else "#8b949e")
                e = l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_parts.append(f'<div style="color:{c}">{e}</div>')
            st.markdown('<div class="logbox">' + "".join(html_parts) + '</div>', unsafe_allow_html=True)
    except:
        pass

    if not lines_shown:
        st.info("No alerts or logs available yet.")


# ------------------------------------------------------------------------------
#  ORDER STATUS
# ------------------------------------------------------------------------------
elif st.session_state.page == "Order Status":

    st.markdown('<div class="sec-title">Order Status</div>', unsafe_allow_html=True)

    tab_all, tab_fill, tab_open, tab_close = st.tabs(
        ["All Orders", "Filled", "Open", "Closed"])

    all_df = pd.DataFrame(th) if th else pd.DataFrame()

    def fmt_df(df):
        if df.empty:
            return df
        df = df.copy()
        df['Time']        = df['timestamp'].str[:19].str.replace("T", " ")
        df['Symbol']      = df['symbol'].str.replace("binance:", "")
        df['PnL']         = df['pnl'].apply(lambda x: f"${float(x):+.4f}")
        df['Exit Price']  = df['exit_price'].apply(lambda x: f"${float(x):,.4f}")
        df['Status']      = df['pnl'].apply(
            lambda x: "Profit" if float(x) > 0 else ("Loss" if float(x) < 0 else "? Flat"))
        return df[['Time', 'Symbol', 'PnL', 'Exit Price', 'Status']]

    with tab_all:
        if not all_df.empty:
            st.dataframe(fmt_df(all_df.tail(30)), use_container_width=True, hide_index=True)
        else:
            st.info("No orders found.")

    with tab_fill:
        if not all_df.empty:
            filled = all_df[all_df['pnl'].apply(float) != 0]
            if not filled.empty:
                st.dataframe(fmt_df(filled.tail(20)), use_container_width=True, hide_index=True)
            else:
                st.info("No filled orders.")
        else:
            st.info("No order data.")

    with tab_open:
        if open_pos:
            rows = [{"Symbol":  p.get("symbol", "").replace("binance:", ""),
                     "Side":    "LONG" if p.get("quantity", 0) > 0 else "SHORT",
                     "Qty":     str(round(abs(p.get("quantity", 0)), 4)),
                     "Entry":   f"${p.get('avg_price', 0):,.4f}",
                     "Status":  "Open"} for p in open_pos]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No open orders.")

    with tab_close:
        if not all_df.empty:
            closed = all_df[all_df['pnl'].apply(float) == 0]
            if not closed.empty:
                st.dataframe(fmt_df(closed.tail(20)), use_container_width=True, hide_index=True)
            else:
                st.info("No closed (flat) orders.")
        else:
            st.info("No order data.")


# ------------------------------------------------------------------------------
#  SIGNALS
# ------------------------------------------------------------------------------
elif st.session_state.page == "Signals":

    st.markdown('<div class="sec-title">TradingView Signals</div>', unsafe_allow_html=True)

    sigs  = read_jsonl(SIGNALS_PATH, n=20)
    total = len(sigs)

    search = st.text_input("Search signals", placeholder="Search by symbol, strategy...",
                           label_visibility="collapsed", key="sig_search")

    if sigs:
        rows_html = ""
        shown = 0
        for s in reversed(sigs):
            if not isinstance(s, dict):
                continue
            # signals.jsonl wraps data under "payload" key
            payload  = s.get("payload", s)
            sym      = str(payload.get("symbol",   s.get("symbol",   ""))).replace("binance:", "")
            action   = str(payload.get("action",   s.get("action",   ""))).upper()
            strategy = str(payload.get("strategy", s.get("strategy", ""))).replace("_", " ")
            price_v  = payload.get("price", s.get("price", 0))
            price    = f"${float(price_v):,.4f}" if price_v else "—"
            tf       = str(payload.get("timeframe", s.get("timeframe", "4h")))
            # parse timestamp from signal_id (TV-<unix_ms>) or direct field
            ts = ""
            sig_id = s.get("signal_id", "")
            if sig_id.startswith("TV-"):
                try:
                    ms = int(sig_id[3:])
                    ts = datetime.fromtimestamp(ms / 1000).strftime("%m-%d %H:%M")
                except:
                    pass
            if not ts:
                ts = str(s.get("timestamp", s.get("time", "")))[:16].replace("T", " ")

            if search and search.lower() not in (sym + strategy + action).lower():
                continue
            if action in ("BUY", "LONG"):
                badge = '<span class="badge-bull">? BUY</span>'
            elif action in ("SELL", "SHORT"):
                badge = '<span class="badge-bear">? SELL</span>'
            elif action == "EXIT":
                badge = '<span class="badge-warn">? EXIT</span>'
            else:
                badge = '<span class="badge-neutral">? Neutral</span>'

            is_exit = payload.get("is_exit", False)
            exit_tag = ' <span style="font-size:10px;color:#d29922">[EXIT]</span>' if is_exit else ""
            rows_html += f"""
            <tr>
              <td style="font-weight:700;color:#58a6ff">{sym}</td>
              <td>{badge}</td>
              <td style="color:#c9d1d9">{strategy}{exit_tag}</td>
              <td style="color:#3fb950;font-weight:600">{price}</td>
              <td style="color:#8b949e">{tf}</td>
              <td style="color:#6e7681;font-size:11px">{ts}</td>
            </tr>"""
            shown += 1

        if rows_html:
            # Summary metrics
            all_actions = []
            for s in sigs:
                p = s.get("payload", s)
                all_actions.append(str(p.get("action", "")).upper())
            buys  = sum(1 for a in all_actions if a in ("BUY","LONG"))
            sells = sum(1 for a in all_actions if a in ("SELL","SHORT"))
            exits = sum(1 for a in all_actions if a == "EXIT")
            sm1, sm2, sm3, sm4 = st.columns(4)
            sm1.metric("Total Signals", total)
            sm2.metric("BUY / LONG",    buys)
            sm3.metric("SELL / SHORT",  sells)
            sm4.metric("EXIT",          exits)
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            st.markdown(f"""
            <div class="tbl-wrap">
            <table>
              <thead><tr>
                <th>SYMBOL</th><th>SIGNAL</th><th>STRATEGY</th>
                <th>PRICE</th><th>TIMEFRAME</th><th>TIME</th>
              </tr></thead>
              <tbody>{rows_html}</tbody>
            </table></div>
            <div style="font-size:12px;color:#6e7681;margin-top:6px">
              Showing {shown} of {total} signal(s) · source: signals.jsonl
            </div>""", unsafe_allow_html=True)
        else:
            st.info("No signals match your search.")
    else:
        st.markdown("""
        <div style='background:#1c2128;border:1px solid #30363d;border-radius:10px;
                    padding:24px;text-align:center;color:#8b949e'>
          <div style='font-size:32px;margin-bottom:10px'>??</div>
          <div style='font-size:15px;font-weight:600;color:#e6edf3;margin-bottom:6px'>No Signals Yet</div>
          <div style='font-size:13px'>Waiting for TradingView webhook signals.<br>
          Set your alert webhook to: <code style='color:#58a6ff'>https://tradingbot.operatorbrief.xyz/webhook</code></div>
        </div>""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
#  BACKTEST ENGINE
# ------------------------------------------------------------------------------
elif st.session_state.page == "Backtest":

    BACKTEST_DATA_DIR = os.path.join(PROJECT_ROOT, "storage/backtest_data")
    SCRIPTS_DIR       = os.path.join(PROJECT_ROOT, "scripts")

    # -- Engine status data -------------------------------------------------
    data_files    = glob.glob(os.path.join(BACKTEST_DATA_DIR, "*.csv"))
    sym_4h        = [os.path.basename(f).replace("_3y_4h.csv","") for f in data_files if "_3y_4h" in f]
    sym_15m       = [os.path.basename(f).replace("_3y_15m.csv","") for f in data_files if "_3y_15m" in f]
    report_files  = glob.glob(os.path.join(REPORTS_DIR, "*.csv"))
    pine_files    = glob.glob(os.path.join(STRATEGIES_DIR, "*4h*.pine"))
    tournament_running = is_process_running("tournament_4h_all_symbols")

    tab_engine, tab_custom, tab_tournament, tab_pine, tab_lab, tab_explorer = st.tabs([
        "Engine Status",
        "Custom Backtest",
        "Tournament Results",
        "Pine Scripts",
        "Alpha Strategy Lab",
        "🔬  Strategy Explorer",
    ])

    # -- TAB 1 — ENGINE STATUS -----------------------------------------------
    with tab_engine:
        st.markdown('<div class="sec-title">Backtesting Engine Status</div>', unsafe_allow_html=True)

        # Status cards row
        e1, e2, e3, e4 = st.columns(4)
        with e1:
            st.markdown(f"""<div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#1f6feb,#388bfd)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">4H Data Files</div>
              <div class="dk-card-value" style="color:#58a6ff">{len(sym_4h)}/16</div>
              <div class="dk-card-sub">{"? All ready" if len(sym_4h)==16 else f"?? {16-len(sym_4h)} missing"}<br>3-year 4H OHLCV</div>
            </div>""", unsafe_allow_html=True)
        with e2:
            st.markdown(f"""<div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Tournament Results</div>
              <div class="dk-card-value" style="color:#3fb950">{"Ready" if t4h_ready else "None"}</div>
              <div class="dk-card-sub">{"? tournament_winners_4h.csv" if t4h_ready else "Run tournament first"}</div>
            </div>""", unsafe_allow_html=True)
        with e3:
            st.markdown(f"""<div class="dk-card">
              <div class="dk-card-accent" style="background:{"linear-gradient(90deg,#3fb950,#56d364)" if tournament_running else "linear-gradient(90deg,#6e7681,#8b949e)"}"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Tournament Engine</div>
              <div class="dk-card-value" style="color:{"#3fb950" if tournament_running else "#6e7681"}">{"RUNNING" if tournament_running else "IDLE"}</div>
              <div class="dk-card-sub">{"tournament_4h_all_symbols.py" if tournament_running else "Ready to run"}</div>
            </div>""", unsafe_allow_html=True)
        with e4:
            pine_count = len(glob.glob(os.path.join(STRATEGIES_DIR, "*4h*.pine")))
            st.markdown(f"""<div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Pine Scripts</div>
              <div class="dk-card-value" style="color:#bc8cff">{pine_count}</div>
              <div class="dk-card-sub">4H universal strategies<br>Ready for TradingView</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # Data files status table
        ecol1, ecol2 = st.columns([3, 2])
        with ecol1:
            st.markdown('<div class="sec-title" style="font-size:13px">Data Files Status</div>', unsafe_allow_html=True)
            file_rows = []
            for sym_name in SYMBOLS_16:
                fname = os.path.join(BACKTEST_DATA_DIR, f"{sym_name}_3y_4h.csv")
                if os.path.exists(fname):
                    sz  = os.path.getsize(fname)
                    mtime = datetime.fromtimestamp(os.path.getmtime(fname)).strftime("%Y-%m-%d %H:%M")
                    try:
                        nrows = sum(1 for _ in open(fname)) - 1
                    except:
                        nrows = 0
                    file_rows.append({"Symbol": sym_name, "Status": "? Ready",
                                      "Rows": str(nrows), "Size": f"{sz/1024:.0f} KB", "Updated": mtime})
                else:
                    file_rows.append({"Symbol": sym_name, "Status": "? Missing",
                                      "Rows": "—", "Size": "—", "Updated": "—"})
            st.dataframe(pd.DataFrame(file_rows), use_container_width=True, hide_index=True, height=320)

        with ecol2:
            st.markdown('<div class="sec-title" style="font-size:13px">Strategy Categories</div>', unsafe_allow_html=True)
            cats = [
                {"Category": "SuperTrend / ATR", "Strategies": "SuperTrend, ATR Band, SMA Cross, EMA Ribbon"},
                {"Category": "Squeeze / Reversion", "Strategies": "Squeeze Momentum, Mean Reversion, Lorentzian"},
                {"Category": "OBV / Flow", "Strategies": "OBV Divergence, WaveTrend, MACD, CMF Flow"},
                {"Category": "SMC / Institutional", "Strategies": "Smart Money, Liquidity Sweep, Order Block"},
            ]
            st.dataframe(pd.DataFrame(cats), use_container_width=True, hide_index=True)

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
            st.markdown('<div class="sec-title" style="font-size:13px">Run Tournament</div>', unsafe_allow_html=True)
            if tournament_running:
                st.warning("Tournament is currently running...")
            else:
                if st.button("Run Full 4H Tournament (All 16 Symbols)", use_container_width=True, type="primary"):
                    try:
                        script = os.path.join(PROJECT_ROOT, "scripts/run_4h_setup_all_symbols.sh")
                        subprocess.Popen(["bash", script], cwd=PROJECT_ROOT,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        st.success("? Tournament started in background! Check Engine Status in ~5 min.")
                    except Exception as ex:
                        st.error(f"? Failed to start: {ex}")
                if len(sym_4h) < 16:
                    if st.button("Download Missing Data First", use_container_width=True):
                        try:
                            script = os.path.join(PROJECT_ROOT, "scripts/fetch_4h_data_all_symbols.py")
                            subprocess.Popen(["python3", script], cwd=PROJECT_ROOT,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            st.success("? Data download started!")
                        except Exception as ex:
                            st.error(f"? {ex}")

    # -- TAB 2 — CUSTOM BACKTEST ----------------------------------------------
    with tab_custom:
        st.markdown('<div class="sec-title">Custom Strategy Backtest</div>', unsafe_allow_html=True)

        cc1, cc2 = st.columns([1, 2])
        with cc1:
            cb_sym = st.selectbox("Symbol", SYMBOLS_16, key="cb_sym")
            cb_strat = st.selectbox("Strategy", [
                "supertrend", "atr_band", "sma_cross", "ema_ribbon",
                "squeeze_momentum", "mean_reversion", "lorentzian",
                "obv_divergence", "wavetrend", "macd_flow", "cmf_flow",
                "smc_liquidity", "order_block",
            ], key="cb_strat")
            cb_mult  = st.slider("Multiplier / Factor", 1.0, 5.0, 3.0, 0.1, key="cb_mult")
            cb_len   = st.slider("Length / Period", 5, 50, 14, 1, key="cb_len")
            cbs1, cbs2 = st.columns(2)
            with cbs1:
                cb_sl = st.number_input("SL %", 0.5, 20.0, 2.0, 0.5, key="cb_sl")
            with cbs2:
                cb_tp = st.number_input("TP %", 1.0, 50.0, 6.0, 0.5, key="cb_tp")

            run_bt = st.button("Run Backtest", use_container_width=True, type="primary", key="run_bt")

        with cc2:
            if run_bt:
                data_file = os.path.join(BACKTEST_DATA_DIR, f"{cb_sym}_3y_4h.csv")
                if not os.path.exists(data_file):
                    st.error(f"? Data file not found: {cb_sym}_3y_4h.csv\nRun data download first.")
                else:
                    with st.spinner(f"Running {cb_strat} on {cb_sym}..."):
                        try:
                            sys.path.insert(0, SCRIPTS_DIR)
                            from my_strategies import apply_strategy
                            df_bt = pd.read_csv(data_file)
                            df_bt.columns = [c.lower() for c in df_bt.columns]
                            df_bt['timestamp'] = pd.to_datetime(df_bt['timestamp'])
                            df_bt = df_bt.sort_values('timestamp').reset_index(drop=True)
                            for col in ['open','high','low','close','volume']:
                                df_bt[col] = pd.to_numeric(df_bt[col], errors='coerce')
                            df_bt = df_bt.dropna()

                            result = apply_strategy(df_bt, cb_strat, optimize=False,
                                                    mult=cb_mult, length=cb_len)

                            if result and isinstance(result, dict):
                                trades  = result.get('trades', [])
                                equity  = result.get('equity_curve', [])
                                metrics = result.get('metrics', {})

                                # Metrics cards
                                m1, m2, m3, m4 = st.columns(4)
                                wr_v   = metrics.get('win_rate', 0) * 100
                                pf_v   = metrics.get('profit_factor', 0)
                                dd_v   = metrics.get('max_drawdown', 0) * 100
                                roi_v  = metrics.get('total_return', 0) * 100
                                m1.metric("Win Rate",       f"{wr_v:.1f}%")
                                m2.metric("Profit Factor",  f"{pf_v:.2f}")
                                m3.metric("Max Drawdown",   f"{dd_v:.1f}%")
                                m4.metric("Total Return",   f"{roi_v:.1f}%")

                                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

                                # Equity curve chart
                                if equity and HAS_PLOTLY:
                                    fig_eq = go.Figure()
                                    fig_eq.add_trace(go.Scatter(
                                        y=equity, mode='lines',
                                        line=dict(color='#3fb950', width=2),
                                        fill='tozeroy',
                                        fillcolor='rgba(63,185,80,0.08)',
                                        name='Equity'))
                                    fig_eq.update_layout(
                                        height=260, margin=dict(l=0,r=0,t=10,b=0),
                                        paper_bgcolor='rgba(0,0,0,0)',
                                        plot_bgcolor='rgba(0,0,0,0)',
                                        xaxis=dict(gridcolor='#21262d',tickfont=dict(size=10,color='#6e7681')),
                                        yaxis=dict(gridcolor='#21262d',tickfont=dict(size=10,color='#6e7681')),
                                        showlegend=False,
                                    )
                                    st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
                                    st.markdown('<div class="chart-title">Equity Curve</div>', unsafe_allow_html=True)
                                    st.plotly_chart(fig_eq, use_container_width=True, config={'displayModeBar': False})
                                    st.markdown('</div>', unsafe_allow_html=True)

                                # Recent trades
                                if trades:
                                    tdf = pd.DataFrame(trades[-20:])
                                    show_cols = [c for c in ['entry_time','exit_time','side','entry_price','exit_price','pnl_pct'] if c in tdf.columns]
                                    if show_cols:
                                        st.markdown("**Last 20 Trades:**")
                                        st.dataframe(tdf[show_cols], use_container_width=True, hide_index=True)

                                # Add to tournament button
                                st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
                                if st.button("? Add This Result to Tournament CSV", key="add_tourn", type="secondary"):
                                    try:
                                        daily_roi = roi_v / (len(df_bt) * 4 / 24 / 365 * 365) if len(df_bt) > 0 else 0
                                        new_row = {
                                            "Symbol": cb_sym,
                                            "Strategy": cb_strat,
                                            "Daily_ROI_%": round(daily_roi, 4),
                                            "Gross_DD_%": round(dd_v, 2),
                                            "Net_DD_%": round(dd_v, 2),
                                            "Max_DD_%": round(dd_v, 2),
                                            "Win_Rate_%": round(wr_v, 2),
                                            "Sharpe_Ratio": round(metrics.get('sharpe', 0), 3),
                                            "Total_Trades": len(trades),
                                            "Tier": "ALPHA++" if daily_roi > 0.3 else "ALPHA" if daily_roi > 0.1 else "BETA",
                                            "Optimal_Mult": cb_mult,
                                            "Optimal_Len": cb_len,
                                            "OOS_Daily_ROI_%": 0,
                                            "OOS_Gross_DD_%": 0,
                                            "OOS_Sharpe": 0,
                                        }
                                        if os.path.exists(TOURNAMENT_4H):
                                            df_exist = read_tournament_csv(TOURNAMENT_4H)
                                            df_new   = pd.concat([df_exist, pd.DataFrame([new_row])], ignore_index=True)
                                        else:
                                            df_new = pd.DataFrame([new_row])
                                        os.makedirs(REPORTS_DIR, exist_ok=True)
                                        df_new.to_csv(TOURNAMENT_4H, index=False)
                                        st.success(f"? Added {cb_sym} / {cb_strat} to tournament results!")
                                    except Exception as ex:
                                        st.error(f"? Failed to save: {ex}")
                            else:
                                st.warning("Backtest returned no results. Check strategy name or data.")
                        except ImportError:
                            st.error("? `my_strategies` module not found in scripts/. Make sure the file exists on the server.")
                        except Exception as ex:
                            st.error(f"? Backtest error: {ex}")
            else:
                st.markdown("""
                <div class="dk-card" style="text-align:center;padding:40px 20px">
                  <div style="font-size:40px;margin-bottom:12px">??</div>
                  <div style="font-size:15px;font-weight:700;color:#e6edf3;margin-bottom:8px">Custom Strategy Backtest</div>
                  <div style="font-size:13px;color:#6e7681">Select a symbol and strategy on the left, then click<br>
                    <b style="color:#58a6ff">Run Backtest</b> to simulate performance on 3 years of 4H data.</div>
                </div>""", unsafe_allow_html=True)

    # -- TAB 3 — TOURNAMENT RESULTS ------------------------------------------
    with tab_tournament:
        st.markdown('<div class="sec-title">Tournament Results — 4H Strategy Analysis</div>', unsafe_allow_html=True)

        if not t4h_ready:
            st.warning("4H Tournament data not generated yet.\n\n"
                       "Run: `bash scripts/run_4h_setup_all_symbols.sh`")
        else:
            df_t     = read_tournament_csv(TOURNAMENT_4H)
            alpha_pp = df_t[df_t['Tier'] == 'ALPHA++'] if 'Tier' in df_t.columns else pd.DataFrame()
            alpha    = df_t[df_t['Tier'] == 'ALPHA']   if 'Tier' in df_t.columns else pd.DataFrame()
            if not df_t.empty and {'Daily_ROI_%', 'Symbol'}.issubset(df_t.columns) and df_t['Daily_ROI_%'].notna().any():
                best_roi = to_float(df_t['Daily_ROI_%'].max(), 0.0)
                best_sym = str(df_t.loc[df_t['Daily_ROI_%'].idxmax(), 'Symbol'])
            else:
                best_roi = 0.0
                best_sym = "—"

            b1, b2, b3, b4 = st.columns(4)
            with b1:
                st.markdown(f"""<div class="dk-card">
                  <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
                  <div class="dk-card-icon">??</div>
                  <div class="dk-card-label">ALPHA++ Strategies</div>
                  <div class="dk-card-value" style="color:#3fb950">{len(alpha_pp)}</div>
                  <div class="dk-card-sub">Elite · ROI &gt; 0.30%/day</div>
                </div>""", unsafe_allow_html=True)
            with b2:
                st.markdown(f"""<div class="dk-card">
                  <div class="dk-card-accent" style="background:linear-gradient(90deg,#58a6ff,#79c0ff)"></div>
                  <div class="dk-card-icon">?</div>
                  <div class="dk-card-label">ALPHA Strategies</div>
                  <div class="dk-card-value" style="color:#58a6ff">{len(alpha)}</div>
                  <div class="dk-card-sub">Strong · ROI &gt; 0.10%/day</div>
                </div>""", unsafe_allow_html=True)
            with b3:
                st.markdown(f"""<div class="dk-card">
                  <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
                  <div class="dk-card-icon">??</div>
                  <div class="dk-card-label">Total Evaluated</div>
                  <div class="dk-card-value" style="color:#bc8cff">{len(df_t)}</div>
                  <div class="dk-card-sub">{df_t['Symbol'].nunique() if 'Symbol' in df_t.columns else 16} symbols · {df_t['Strategy'].nunique() if 'Strategy' in df_t.columns else 28} strategies</div>
                </div>""", unsafe_allow_html=True)
            with b4:
                st.markdown(f"""<div class="dk-card">
                  <div class="dk-card-accent" style="background:linear-gradient(90deg,#d29922,#e3b341)"></div>
                  <div class="dk-card-icon">??</div>
                  <div class="dk-card-label">Best Daily ROI</div>
                  <div class="dk-card-value" style="color:#d29922">{best_roi:.3f}%</div>
                  <div class="dk-card-sub">{best_sym}</div>
                </div>""", unsafe_allow_html=True)

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            if HAS_PLOTLY and {'Daily_ROI_%', 'Symbol'}.issubset(df_t.columns) and not alpha_pp.empty:
                bc1, bc2 = st.columns([3, 2])
                with bc1:
                    st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
                    st.markdown('<div class="chart-title">ROI by Symbol (ALPHA++)</div>', unsafe_allow_html=True)
                    bps = (alpha_pp.sort_values('Daily_ROI_%', ascending=False)
                           .groupby('Symbol').first().reset_index()
                           .sort_values('Daily_ROI_%'))
                    fig3 = go.Figure(go.Bar(
                        x=bps['Daily_ROI_%'], y=bps['Symbol'], orientation='h',
                        marker_color=['#3fb950' if v >= 0.3 else '#56d364' for v in bps['Daily_ROI_%']],
                        text=[f"{v:.3f}%" for v in bps['Daily_ROI_%']],
                        textposition='outside', textfont=dict(size=10, color='#8b949e'),
                    ))
                    fig3.update_layout(
                        height=280, margin=dict(l=0, r=60, t=0, b=0),
                        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        xaxis=dict(gridcolor='#21262d', ticksuffix='%',
                                   tickfont=dict(size=10, color='#6e7681'), linecolor='#30363d'),
                        yaxis=dict(tickfont=dict(size=11, color='#c9d1d9'), linecolor='#30363d'),
                        showlegend=False, font=dict(color='#8b949e'),
                    )
                    st.plotly_chart(fig3, use_container_width=True, config={'displayModeBar': False})
                    st.markdown('</div>', unsafe_allow_html=True)

                with bc2:
                    st.markdown('<div class="chart-panel">', unsafe_allow_html=True)
                    st.markdown('<div class="chart-title">Strategy Distribution</div>', unsafe_allow_html=True)
                    if 'Strategy' in alpha_pp.columns:
                        sc = alpha_pp['Strategy'].value_counts().reset_index()
                        sc.columns = ['Strategy', 'Count']
                        sc['Strategy'] = sc['Strategy'].str[:20]
                        fig4 = go.Figure(go.Pie(
                            labels=sc['Strategy'], values=sc['Count'], hole=0.55,
                            marker_colors=['#1f6feb','#388bfd','#58a6ff','#3fb950','#56d364','#bc8cff'],
                            textinfo='label+percent', textfont_size=10, textfont_color='#e6edf3',
                        ))
                        fig4.update_layout(
                            height=280, margin=dict(l=0, r=0, t=0, b=0),
                            paper_bgcolor='rgba(0,0,0,0)', showlegend=False,
                            annotations=[dict(text=f'<b style="color:#e6edf3">{len(alpha_pp)}<br>Combos</b>',
                                              x=0.5, y=0.5, font_size=12,
                                              showarrow=False, font_color='#e6edf3')]
                        )
                        st.plotly_chart(fig4, use_container_width=True, config={'displayModeBar': False})
                    st.markdown('</div>', unsafe_allow_html=True)

            with st.expander("Top ALPHA++ Results", expanded=True):
                top = alpha_pp.sort_values("Daily_ROI_%", ascending=False).head(30) if not alpha_pp.empty else pd.DataFrame()
                if not top.empty:
                    cols = [c for c in ["Symbol","Strategy","Daily_ROI_%","Gross_DD_%","Net_DD_%",
                                        "Win_Rate_%","Sharpe_Ratio","Total_Trades","Tier"] if c in top.columns]
                    st.dataframe(top[cols], use_container_width=True, hide_index=True)

            if not alpha.empty:
                with st.expander("? ALPHA Results"):
                    top_a = alpha.sort_values("Daily_ROI_%", ascending=False).head(20)
                    cols  = [c for c in ["Symbol","Strategy","Daily_ROI_%","Gross_DD_%","Net_DD_%",
                                         "Win_Rate_%","Sharpe_Ratio","Total_Trades","Tier"] if c in top_a.columns]
                    st.dataframe(top_a[cols], use_container_width=True, hide_index=True)


            # OOS Validated Premium Strategies
            oos_col_check = "OOS_Daily_ROI_%" in df_t.columns and "OOS_Gross_DD_%" in df_t.columns
            if oos_col_check:
                with st.expander("PREMIUM OOS-Validated Strategies (ROI>1% + GDD>-35%)", expanded=True):
                    st.markdown("<div style='font-size:12px;color:#6e7681;margin-bottom:8px'>Out-of-Sample validated. Trained 80%, tested on unseen 20% data. Most reliable for live trading.</div>", unsafe_allow_html=True)
                    elite_mask = (df_t["OOS_Daily_ROI_%"] >= 1.0) & (df_t["OOS_Gross_DD_%"] >= -35.0)
                    elite = df_t[elite_mask].sort_values("OOS_Daily_ROI_%", ascending=False).copy()
                    if not elite.empty:
                        show_cols = [c for c in ["Symbol","Strategy","Tier","OOS_Daily_ROI_%","OOS_Gross_DD_%","OOS_Sharpe","Optimal_SL_%","Optimal_TP_%","Win_Rate_%","Total_Trades"] if c in elite.columns]
                        st.dataframe(elite[show_cols].reset_index(drop=True), use_container_width=True, hide_index=True)
                        st.markdown("<div style='font-size:12px;font-weight:700;color:#e6edf3;margin:10px 0 6px'>Top 5 Elite Combos</div>", unsafe_allow_html=True)
                        top5 = elite.head(5)
                        cols5 = st.columns(5)
                        _colors5 = ["#3fb950","#58a6ff","#bc8cff","#d29922","#f78166"]
                        for i5, (_, r5) in enumerate(top5.iterrows()):
                            with cols5[i5]:
                                roi5 = to_float(r5.get("OOS_Daily_ROI_%", 0), 0.0)
                                gdd5 = to_float(r5.get("OOS_Gross_DD_%", 0), 0.0)
                                sym5 = r5.get("Symbol","")
                                stg5 = str(r5.get("Strategy",""))[:18]
                                c5   = _colors5[i5]
                                st.markdown(f"<div class='dk-card' style='padding:10px 8px;text-align:center'><div class='dk-card-accent' style='background:{c5}'></div><div style='font-size:10px;color:#6e7681;margin-bottom:4px'>{sym5}</div><div style='font-size:9px;color:#8b949e;margin-bottom:6px'>{stg5}</div><div style='font-size:15px;font-weight:900;color:{c5}'>{roi5:.2f}%</div><div style='font-size:9px;color:#6e7681'>ROI/day</div><div style='font-size:11px;color:#f85149;margin-top:4px'>GDD {gdd5:.1f}%</div></div>", unsafe_allow_html=True)
                    else:
                        st.info("No elite strategies yet. Run the premium tournament first.")

    # -- TAB 4 — PINE SCRIPTS ------------------------------------------------
    with tab_pine:
        st.markdown('<div class="sec-title">Symbol-Optimized Pine Scripts</div>', unsafe_allow_html=True)

        # Premium strategies highlight cards
        # Premium scripts — read live from tournament CSV
        st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>Top Premium Scripts (ALPHA++) — Live Data from Tournament</div>", unsafe_allow_html=True)
        _PREM_MAP = [
            ("OPUSDT",   "82 chandelier exit",  "OPUSDT_82_chandelier_exit_4h.pine"),
            ("SUIUSDT",  "82 chandelier exit",  "SUIUSDT_82_chandelier_exit_4h.pine"),
            ("DOTUSDT",  "82 chandelier exit",  "DOTUSDT_82_chandelier_exit_4h.pine"),
            ("AVAXUSDT", "72 hull ma trend",    "AVAXUSDT_72_hull_ma_trend_4h.pine"),
            ("AVAXUSDT", "71 stoch rsi power",  "AVAXUSDT_71_stoch_rsi_power_4h.pine"),
            ("APTUSDT",  "75 mfi reversal",     "APTUSDT_75_mfi_reversal_4h.pine"),
            ("FILUSDT",  "86 bb squeeze break", "FILUSDT_86_bb_squeeze_break_4h.pine"),
        ]
        _PCLRS = ["#3fb950","#58a6ff","#bc8cff","#d29922","#f78166","#56d364","#79c0ff"]
        # Load live numbers from CSV
        try:
            _df_t2 = read_tournament_csv(TOURNAMENT_4H)
        except Exception:
            _df_t2 = pd.DataFrame()

        _pc = st.columns(4)
        for _pi, (_psym, _pstrat_key, _pfile) in enumerate(_PREM_MAP):
            _ppath = os.path.join(STRATEGIES_DIR, _pfile)
            _clr   = _PCLRS[_pi % len(_PCLRS)]
            # Pull exact numbers from CSV
            _proi, _pgdd, _psh, _psl, _ptp = 0.0, 0.0, 0.0, 0.5, 12.0
            if not _df_t2.empty and {"Symbol", "Strategy"}.issubset(_df_t2.columns):
                _mask = (_df_t2["Symbol"] == _psym) & (_df_t2["Strategy"] == _pstrat_key)
                if _mask.any():
                    _r = _df_t2[_mask].iloc[0]
                    _proi = to_float(_r.get("OOS_Daily_ROI_%", 0), 0.0)
                    _pgdd = to_float(_r.get("OOS_Gross_DD_%",  0), 0.0)
                    _psh  = to_float(_r.get("OOS_Sharpe",      0), 0.0)
                    _psl  = to_float(_r.get("Optimal_SL_%",  0.5), 0.5)
                    _ptp  = to_float(_r.get("Optimal_TP_%",  12.0), 12.0)
            with _pc[_pi % 4]:
                st.markdown(f"""<div style='background:#161b22;border:1px solid {_clr}40;border-radius:8px;padding:10px 8px;margin-bottom:6px;text-align:center'>
                  <div style='font-size:11px;font-weight:700;color:{_clr}'>{_psym}</div>
                  <div style='font-size:9px;color:#8b949e;margin:2px 0 6px'>{_pstrat_key.title()}</div>
                  <div style='font-size:14px;font-weight:900;color:{_clr}'>{_proi:.4f}%</div>
                  <div style='font-size:9px;color:#6e7681'>OOS ROI/day</div>
                  <div style='font-size:11px;color:#f85149;margin:3px 0'>GDD {_pgdd:.2f}%</div>
                  <div style='font-size:9px;color:#6e7681'>Sharpe {_psh:.2f} | SL {_psl}% | TP {_ptp}%</div>
                </div>""", unsafe_allow_html=True)
                try:
                    _pcode = open(_ppath, encoding="utf-8").read()
                    st.download_button(
                        label=f"Download {_psym} Pine Script",
                        data=_pcode, file_name=_pfile,
                        mime="text/plain", use_container_width=True,
                        key=f"pm_{_pfile}"
                    )
                except Exception:
                    st.warning(f"File not found: {_pfile}")
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        st.divider()

        all_pfiles = sorted(glob.glob(os.path.join(STRATEGIES_DIR, "*4h*.pine")))
        # Split: symbol-specific (contain USDT) vs generic templates
        sym_pfiles  = [f for f in all_pfiles if any(s in os.path.basename(f) for s in SYMBOLS_16)]
        tmpl_pfiles = [f for f in all_pfiles if f not in sym_pfiles]

        # Filter controls
        fc1, fc2, fc3 = st.columns([2, 2, 1])
        with fc1:
            sym_filter = st.selectbox("Filter by Symbol", ["All"] + sorted(SYMBOLS_16), key="pine_sym")
        with fc2:
            strat_types = ["All", "chandelier_exit", "hull_ma", "bb_squeeze",
                           "stoch_rsi", "mfi_reversal", "ichimoku_trend_pro",
                           "aggressive_entry", "macd_breakout", "keltner_breakout", "ichimoku_macd_pro"]
            strat_filter = st.selectbox("Filter by Strategy", strat_types, key="pine_strat")
        with fc3:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            st.markdown(f"<div style='color:#58a6ff;font-size:13px;font-weight:700'>{len(sym_pfiles)} scripts</div>",
                        unsafe_allow_html=True)

        # Apply filters
        filtered = sym_pfiles
        if sym_filter != "All":
            filtered = [f for f in filtered if sym_filter in os.path.basename(f)]
        if strat_filter != "All":
            filtered = [f for f in filtered if strat_filter in os.path.basename(f)]

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        if filtered:
            # Group by symbol
            from collections import defaultdict
            by_sym = defaultdict(list)
            for f in filtered:
                nm = os.path.basename(f)
                sym_found = next((s for s in SYMBOLS_16 if nm.startswith(s)), "Other")
                by_sym[sym_found].append(f)

            for sym_name in sorted(by_sym.keys()):
                files_for_sym = sorted(by_sym[sym_name])
                with st.expander(f"?? {sym_name}  ({len(files_for_sym)} scripts)", expanded=(len(by_sym)==1)):
                    cols4 = st.columns(3)
                    for i, fp2 in enumerate(files_for_sym):
                        nm = os.path.basename(fp2)
                        short_nm = nm.replace(sym_name + "_", "").replace("_4h.pine", "").replace("_", " ")
                        try:
                            with open(fp2, "r", encoding="utf-8", errors="ignore") as f:
                                code2 = f.read()
                            # Extract ROI from header comment
                            roi_match = __import__("re").search(r"Daily ROI:\s*([0-9.]+)%", code2)
                            roi_str = f"  ROI={roi_match.group(1)}%" if roi_match else ""
                            with cols4[i % 3]:
                                st.download_button(
                                    f"?? {short_nm}{roi_str}",
                                    code2, file_name=nm,
                                    mime="text/plain", use_container_width=True,
                                    key=f"dl_{nm}"
                                )
                        except:
                            pass
        else:
            st.info("No scripts match your filter.")

        st.divider()

        # Generic templates section
        st.markdown('<div class="sec-title" style="font-size:13px">Generic Template Scripts</div>',
                    unsafe_allow_html=True)
        if tmpl_pfiles:
            tcols = st.columns(3)
            for i, fp2 in enumerate(tmpl_pfiles):
                nm = os.path.basename(fp2)
                try:
                    with open(fp2, "r", encoding="utf-8", errors="ignore") as f:
                        code2 = f.read()
                    with tcols[i % 3]:
                        st.download_button(f"?? {nm}", code2, file_name=nm,
                                           mime="text/plain", use_container_width=True,
                                           key=f"tmpl_{nm}")
                except:
                    pass

        st.divider()
        st.markdown("""
        <div class="dk-card">
          <div class="dk-card-label">How to use Pine Scripts in TradingView</div>
          <ol style="color:#c9d1d9;font-size:13px;margin:8px 0 0 16px;line-height:2">
            <li>Open TradingView ? Set chart to <b style="color:#58a6ff">4H timeframe</b></li>
            <li>Open Pine Script Editor ? click <b style="color:#58a6ff">Open</b> ? paste the downloaded code</li>
            <li>Click <b style="color:#3fb950">Add to chart</b> ? check <b>Strategy Tester</b> tab</li>
            <li>If Net Profit is positive ? click <b style="color:#d29922">Alert ? Create</b></li>
            <li>Set webhook URL to your server and use JSON message format</li>
          </ol>
        </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="sec-title" style="font-size:13px">16 Symbols — Tournament Status</div>', unsafe_allow_html=True)
        if t4h_ready:
            df_t2 = read_tournament_csv(TOURNAMENT_4H)
            if not df_t2.empty and {'Daily_ROI_%', 'Symbol'}.issubset(df_t2.columns):
                bps3  = (df_t2.sort_values("Daily_ROI_%", ascending=False)
                         .groupby("Symbol").first().reset_index()
                         .sort_values("Daily_ROI_%", ascending=False))
                sm = {
                    str(r.get("Symbol", "")).upper(): r
                    for _, r in bps3.iterrows()
                    if str(r.get("Symbol", "")).strip()
                }
            else:
                sm = {}
            sym_rows = []
            for sym_name in SYMBOLS_16:
                d = sm.get(sym_name.upper())
                if d is not None:
                    _daily_roi = to_float(d.get("Daily_ROI_%", 0), 0.0)
                    _win_rate = to_float(d.get("Win_Rate_%", 0), 0.0)
                    sym_rows.append({"Symbol": sym_name, "Status": "? Ready",
                                     "Best Strategy": str(d.get("Strategy", ""))[:30],
                                     "Daily ROI": f"{_daily_roi:.3f}%",
                                     "Win Rate": f"{_win_rate:.1f}%",
                                     "Tier": str(d.get("Tier", ""))})
                else:
                    sym_rows.append({"Symbol": sym_name, "Status": "Needs run",
                                     "Best Strategy": "Run tournament",
                                     "Daily ROI": "—", "Win Rate": "—", "Tier": "—"})
            st.dataframe(pd.DataFrame(sym_rows), use_container_width=True, hide_index=True)
        else:
            st.warning("Run the 4H tournament first: `bash scripts/run_4h_setup_all_symbols.sh`")


# ------------------------------------------------------------------------------
    # ──────────────────────────────────────────────────────────────────────
    # TAB 6 — STRATEGY EXPLORER (Phase 4E + 4B)
    # ──────────────────────────────────────────────────────────────────────
    with tab_explorer:
        st.markdown('<div class="sec-title">🔬 Strategy Explorer — Discovered Candidates</div>', unsafe_allow_html=True)

        explorer_csv = os.path.join(REPORTS_DIR, "explorer_winners.csv")
        ensemble_csv = os.path.join(REPORTS_DIR, "ensemble_winners.csv")
        candidates_csv = os.path.join(REPORTS_DIR, "candidates_top10.csv")
        enriched_csv = os.path.join(REPORTS_DIR, "tournament_winners_enriched.csv")

        col1, col2, col3 = st.columns(3)
        with col1:
            explorer_count = 0
            if os.path.exists(explorer_csv):
                try:
                    explorer_count = len(pd.read_csv(explorer_csv))
                except Exception:
                    pass
            st.metric("V2 Explorer Strategies", explorer_count)
        with col2:
            ensemble_count = 0
            if os.path.exists(ensemble_csv):
                try:
                    ensemble_count = len(pd.read_csv(ensemble_csv))
                except Exception:
                    pass
            st.metric("Ensemble Combinations", ensemble_count)
        with col3:
            last_top10_mtime = "N/A"
            if os.path.exists(candidates_csv):
                from datetime import datetime as _dt
                last_top10_mtime = _dt.fromtimestamp(
                    os.path.getmtime(candidates_csv)
                ).strftime("%Y-%m-%d %H:%M")
            st.metric("Top-10 Last Updated", last_top10_mtime)

        st.markdown("---")

        st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>Daily Top-10 Candidates (diversified by source)</div>", unsafe_allow_html=True)
        if os.path.exists(candidates_csv):
            try:
                top = pd.read_csv(candidates_csv)
                cols_to_show = ["Rank", "Strategy", "Symbol", "Source",
                                "Daily_ROI_%", "Gross_DD_%", "Win_Rate_%",
                                "Total_Trades", "Risk_Adjusted_Score",
                                "Calmar_Ratio", "WFA_Consistency"]
                cols_to_show = [c for c in cols_to_show if c in top.columns]
                st.dataframe(top[cols_to_show], use_container_width=True, hide_index=True)
            except Exception as _exc:
                st.warning(f"Could not load top-10: {_exc}")
        else:
            st.info("No top-10 file yet. The daily report cron at 02:45 UTC will generate it.")

        st.markdown("---")

        col_exp, col_ens = st.columns(2)
        with col_exp:
            st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>V2 Explorer — Top single-indicator strategies</div>", unsafe_allow_html=True)
            if os.path.exists(explorer_csv):
                try:
                    expl = pd.read_csv(explorer_csv).head(15)
                    cols = ["Symbol","Strategy","Daily_ROI_%","Gross_DD_%","Win_Rate_%","Total_Trades","Sharpe_Ratio"]
                    cols = [c for c in cols if c in expl.columns]
                    st.dataframe(expl[cols], use_container_width=True, hide_index=True, height=420)
                except Exception as _exc:
                    st.warning(f"Explorer CSV read error: {_exc}")
            else:
                st.info("No explorer output yet.")
        with col_ens:
            st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>Ensemble — Top strategy combinations</div>", unsafe_allow_html=True)
            if os.path.exists(ensemble_csv):
                try:
                    ens = pd.read_csv(ensemble_csv).head(15)
                    cols = ["Symbol","Strategy","Daily_ROI_%","Gross_DD_%","Win_Rate_%","Total_Trades","Sharpe_Ratio"]
                    cols = [c for c in cols if c in ens.columns]
                    st.dataframe(ens[cols], use_container_width=True, hide_index=True, height=420)
                except Exception as _exc:
                    st.warning(f"Ensemble CSV read error: {_exc}")
            else:
                st.info("No ensemble output yet.")

        st.markdown("---")
        st.markdown(
            "<div style='font-size:11px;color:#8b949e;line-height:1.5'>"
            "<b>Explorer</b> runs 12 real indicator strategies (RSI, BB, MACD, Stoch, "
            "Williams %R, ATR breakout, Donchian, ADX trend, OBV, Triple EMA, RSI divergence) "
            "against BTC/ETH/SOL/BNB/AVAX 4h data with per-trade SL/TP. "
            "<b>Ensemble</b> combines pairs of strategies via AND/OR/MAJORITY voting. "
            "Combined with advanced_metrics (Calmar, Sortino, MC DD, WFA, binomial significance) "
            "and diversified top-10 selection in the daily report."
            "</div>",
            unsafe_allow_html=True,
        )


# ------------------------------------------------------------------------------
#  LIGHTER DEX

    # -- TAB 5 — STRATEGY LAB --------------------------------------------------
    with tab_lab:
        st.markdown('<div class="sec-title">Alpha Strategy Lab — Separate Backtest Engine</div>', unsafe_allow_html=True)
        st.markdown("""<div style='font-size:12px;color:#6e7681;margin-bottom:12px'>
        This pipeline is separate from live execution. It first generates or ingests TradingView-style trade CSVs,
        then verifies alpha candidates using your rule:
        <b>ROI/day &gt; 1%</b> and <b>|Gross DD|, |Net DD| &lt; 20%</b>.
        Qualified strategies get webhook-ready Pine copies with embedded JSON + secret.</div>""",
        unsafe_allow_html=True)

        # Paths for backtest result CSVs
        VAL_CSV  = ALPHA_VAL_CSV
        ALL_CSV  = ALPHA_ALL_CSV
        BEST_CSV = ALPHA_BEST_CSV
        SHORTLIST_CSV = ALPHA_SHORTLIST_CSV

        # -- Run backtest button ----------------------------------------------
        rb1, rb2 = st.columns([1, 4])
        with rb1:
            run_bt = st.button("Run Alpha Pipeline", use_container_width=True, key="run_lab_bt")
        with rb2:
            st.markdown("<div style='font-size:11px;color:#6e7681;padding-top:10px'>Runs the separate backtest engine, writes alpha reports to storage/reports, generates webhook-ready Pine files, and sends Telegram notifications for alpha candidates.</div>",
                        unsafe_allow_html=True)

        if run_bt:
            with st.spinner("Running alpha backtest pipeline..."):
                import subprocess as _sp
                _r = _sp.run(
                    [
                        '/home/ubuntu/tradingview_webhook_bot/venv/bin/python3',
                        '/home/ubuntu/tradingview_webhook_bot/scripts/run_alpha_pipeline.py',
                        '--notify-telegram',
                    ],
                    capture_output=True, text=True,
                    cwd='/home/ubuntu/tradingview_webhook_bot', timeout=1800
                )
            if _r.returncode == 0:
                st.success("Alpha pipeline complete. Reports and Pine files reloaded below.")
            else:
                st.error("Alpha pipeline failed: " + (_r.stderr or _r.stdout)[:500])

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # -- Load validated CSV -----------------------------------------------
        _val_exists  = os.path.exists(VAL_CSV)
        _best_exists = os.path.exists(BEST_CSV)
        _all_exists  = os.path.exists(ALL_CSV)
        _short_exists = os.path.exists(SHORTLIST_CSV)
        _status      = load_json(ALPHA_STATUS)

        if not _val_exists:
            st.info("No alpha results yet. Click **Run Alpha Pipeline** to generate them.")
        else:
            try:
                _df_val  = read_csv_safe(VAL_CSV)
                _df_best = read_csv_safe(BEST_CSV) if _best_exists else pd.DataFrame()
                _df_all  = read_csv_safe(ALL_CSV) if _all_exists else pd.DataFrame()
                _df_short = read_csv_safe(SHORTLIST_CSV) if _short_exists else pd.DataFrame()
            except Exception as _e:
                st.error(f"Error loading alpha results: {_e}")
                _df_val = pd.DataFrame()
                _df_best = pd.DataFrame()
                _df_all = pd.DataFrame()
                _df_short = pd.DataFrame()

            if not _df_val.empty:
                # -- Summary cards --------------------------------------------
                _sc1, _sc2, _sc3, _sc4 = st.columns(4)
                _best_roi = to_float(_df_val['ROI_Per_Day_Pct'].max(), 0.0) if 'ROI_Per_Day_Pct' in _df_val.columns else 0.0
                _best_sh  = to_float(_df_val['Sharpe_Ratio'].max(), 0.0) if 'Sharpe_Ratio' in _df_val.columns else 0.0
                _webhook_ready = int((_df_val.get('Webhook_Ready', pd.Series(dtype='object')) == 'YES').sum())
                _short_count = len(_df_short) if not _df_short.empty else int(_status.get("shortlist_count", 0))
                _last_run = _status.get("generated_at_utc", "")
                _last_run_display = _last_run.replace("T", " ").replace("Z", " UTC") if _last_run else "Unknown"
                with _sc1:
                    st.markdown(f"""<div class="dk-card">
                      <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
                      <div class="dk-card-icon">A</div>
                      <div class="dk-card-label">Alpha Strategies</div>
                      <div class="dk-card-value" style="color:#3fb950">{len(_df_val)}</div>
                      <div class="dk-card-sub">ROI/day &gt; 1% and DD under 20%</div></div>""", unsafe_allow_html=True)
                with _sc2:
                    st.markdown(f"""<div class="dk-card">
                      <div class="dk-card-accent" style="background:linear-gradient(90deg,#58a6ff,#79c0ff)"></div>
                      <div class="dk-card-icon">ROI</div>
                      <div class="dk-card-label">Best ROI/day</div>
                      <div class="dk-card-value" style="color:#58a6ff">{_best_roi:.4f}%</div>
                      <div class="dk-card-sub">Alpha-qualified only</div></div>""", unsafe_allow_html=True)
                with _sc3:
                    st.markdown(f"""<div class="dk-card">
                      <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
                      <div class="dk-card-icon">SR</div>
                      <div class="dk-card-label">Shortlist / Sharpe</div>
                      <div class="dk-card-value" style="color:#bc8cff">{_short_count} / {_best_sh:.2f}</div>
                      <div class="dk-card-sub">{_webhook_ready} webhook-ready Pine files</div></div>""", unsafe_allow_html=True)
                with _sc4:
                    st.markdown(f"""<div class="dk-card">
                      <div class="dk-card-accent" style="background:linear-gradient(90deg,#d29922,#e3b341)"></div>
                      <div class="dk-card-icon">RUN</div>
                      <div class="dk-card-label">Last Run</div>
                      <div class="dk-card-value" style="color:#d29922;font-size:14px">{_last_run_display}</div>
                      <div class="dk-card-sub">{_status.get("all_results_count", len(_df_all))} files analyzed</div></div>""", unsafe_allow_html=True)

                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

                # -- Alpha strategy cards with Pine download -------------------
                st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>Alpha Candidates — Webhook-Ready Pine Scripts</div>",
                            unsafe_allow_html=True)

                _CLRS2 = ["#3fb950","#58a6ff","#bc8cff","#d29922","#f78166","#56d364","#79c0ff","#ffa657"]
                _df_val_s = _df_val.sort_values('ROI_Per_Day_Pct', ascending=False) if 'ROI_Per_Day_Pct' in _df_val.columns else _df_val

                for _vi, (_, _vrow) in enumerate(_df_val_s.iterrows()):
                    _vsym   = str(_vrow.get('Symbol',   ''))
                    _vstrat = str(_vrow.get('Strategy', ''))
                    _vtp    = to_float(_vrow.get('TP_Pct', 0), 0.0)
                    _vsl    = to_float(_vrow.get('SL_Pct', 0), 0.0)
                    _vroi   = to_float(_vrow.get('ROI_Per_Day_Pct', 0), 0.0)
                    _vgdd   = to_float(_vrow.get('Gross_Drawdown_Percent', 0), 0.0)
                    _vndd   = to_float(_vrow.get('Net_Drawdown_Percent', 0), 0.0)
                    _vwr    = to_float(_vrow.get('Win_Rate_Percent', 0), 0.0)
                    _vsh    = to_float(_vrow.get('Sharpe_Ratio', 0), 0.0)
                    _vpf    = to_float(_vrow.get('Profit_Factor', 0), 0.0)
                    _vtr    = int(to_float(_vrow.get('Total_Trades', 0), 0.0))
                    _vrs    = to_float(_vrow.get('Reality Score', 0), 0.0)
                    _voos   = to_float(_vrow.get('OOS ROI %', 0), 0.0)
                    _vwf    = to_float(_vrow.get('WF Pass Rate %', 0), 0.0)
                    _vgrade = _vrow.get('Performance_Grade', '')
                    _vstatus= _vrow.get('Deployment_Status', '')
                    _vreason= str(_vrow.get('Alpha_Reason', ''))
                    _vsource= str(_vrow.get('Source_CSV', ''))
                    _vclr   = _CLRS2[_vi % len(_CLRS2)]

                    _pine_path = str(_vrow.get('Generated_Pine_Script', '')).strip()
                    _pine_name = os.path.basename(_pine_path) if _pine_path else ""

                    with st.expander(f"{'?' if _pine_path else '??'} {_vsym}  |  {_vstrat}  |  ROI {_vroi:.4f}%/day  |  GDD {_vgdd:.2f}%", expanded=(_vi==0)):
                        _mc1, _mc2 = st.columns([1.2, 2])

                        with _mc1:
                            st.markdown(f"""<div style='background:#161b22;border:1px solid {_vclr}40;border-radius:8px;padding:14px'>
                              <div style='font-size:11px;color:#6e7681;margin-bottom:8px'>ALPHA BACKTEST METRICS</div>
                              <table style='width:100%;font-size:12px;color:#c9d1d9'>
                              <tr><td>ROI / day</td><td style='color:{_vclr};font-weight:700;text-align:right'>{_vroi:.4f}%</td></tr>
                              <tr><td>ROI / year</td><td style='color:{_vclr};text-align:right'>{to_float(_vrow.get("ROI_Annual_Percent",0), 0.0):.1f}%</td></tr>
                              <tr><td>Win Rate</td><td style='color:{"#3fb950" if _vwr>=50 else "#f85149"};text-align:right'>{_vwr:.1f}%</td></tr>
                              <tr><td>Profit Factor</td><td style='text-align:right'>{_vpf:.2f}</td></tr>
                              <tr><td>Sharpe Ratio</td><td style='text-align:right'>{_vsh:.2f}</td></tr>
                              <tr><td>Reality Score</td><td style='text-align:right'>{_vrs:.1f}</td></tr>
                              <tr><td>OOS ROI</td><td style='text-align:right'>{_voos:.2f}%</td></tr>
                              <tr><td>WF Pass Rate</td><td style='text-align:right'>{_vwf:.1f}%</td></tr>
                              <tr><td>Gross DD</td><td style='color:#f85149;text-align:right'>{_vgdd:.2f}%</td></tr>
                              <tr><td>Net DD</td><td style='color:#f85149;text-align:right'>{_vndd:.2f}%</td></tr>
                              <tr><td>SL / TP</td><td style='text-align:right'>{_vsl}% / {_vtp}%</td></tr>
                              <tr><td>Total Trades</td><td style='text-align:right'>{_vtr}</td></tr>
                              <tr><td>Grade</td><td style='color:{_vclr};font-weight:700;text-align:right'>{_vgrade}</td></tr>
                              <tr><td>Status</td><td style='text-align:right'>{_vstatus}</td></tr>
                              <tr><td>Webhook Ready</td><td style='text-align:right'>{_vrow.get("Webhook_Ready","NO")}</td></tr>
                              </table>
                            </div>""", unsafe_allow_html=True)
                            st.markdown(f"<div style='font-size:11px;color:#8b949e;margin-top:8px'><b>Reason:</b> {_vreason}<br><b>Source CSV:</b> {os.path.basename(_vsource)}</div>",
                                        unsafe_allow_html=True)

                        with _mc2:
                            if _pine_path and os.path.exists(_pine_path):
                                try:
                                    _pine_code = open(_pine_path, encoding='utf-8', errors='ignore').read()
                                    st.download_button(
                                        label=f"Download Webhook-Ready Pine — {_vsym} {_vstrat}",
                                        data=_pine_code, file_name=os.path.basename(_pine_path),
                                        mime="text/plain", use_container_width=True,
                                        key=f"lab_dl_{_vi}"
                                    )
                                    st.code(_pine_code[:1200] + ("\n......" if len(_pine_code) > 1200 else ""),
                                            language="javascript")
                                except Exception as _pe:
                                    st.warning(f"Could not read generated pine: {_pe}")
                            else:
                                st.warning("No webhook-ready Pine copy generated for this strategy.")
                                st.markdown(f"<div style='font-size:11px;color:#6e7681'>Generated scripts directory: {ALPHA_SCRIPTS_DIR}</div>",
                                            unsafe_allow_html=True)

                # -- Alert setup guide -----------------------------------------
                st.divider()
                st.markdown("""<div class="dk-card" style="padding:14px">
                  <div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:8px'>TradingView Alert Setup</div>
                  <div style='font-size:12px;color:#8b949e;line-height:2'>
                  <b style='color:#58a6ff'>Step 1:</b> Download the webhook-ready Pine script from this Alpha Lab<br>
                  <b style='color:#58a6ff'>Step 2:</b> Open TradingView on the matching symbol and timeframe shown above<br>
                  <b style='color:#58a6ff'>Step 3:</b> Paste the script in Pine Editor and add it to the chart<br>
                  <b style='color:#58a6ff'>Step 4:</b> Create alerts using <b>Webhook BUY</b> and <b>Webhook SELL</b><br>
                  <b style='color:#58a6ff'>Step 5:</b> Webhook URL: <code>https://tradingbot.operatorbrief.xyz/webhook/tradingview</code><br>
                  <b style='color:#58a6ff'>Step 6:</b> Do not type custom JSON in the message box. The generated alpha script already embeds JSON and the webhook secret.
                  </div></div>""", unsafe_allow_html=True)

                # -- Best per symbol table -----------------------------------------
                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

                if not _df_short.empty:
                    st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:6px'>Frozen Paper-Trade Shortlist</div>",
                                unsafe_allow_html=True)
                    _show_short_cols = [c for c in ['Shortlist Rank','Symbol','Strategy','Timeframe','Reality Score','OOS ROI %',
                                                    'WF Pass Rate %','ROI_Per_Day_Pct','Gross_Drawdown_Percent',
                                                    'Net_Drawdown_Percent','Shortlist Status'] if c in _df_short.columns]
                    st.dataframe(_df_short[_show_short_cols].reset_index(drop=True),
                                 use_container_width=True, hide_index=True)
                    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
                st.markdown("<div style='font-size:13px;font-weight:700;color:#e6edf3;margin-bottom:6px'>Best Strategy Per Symbol</div>",
                            unsafe_allow_html=True)
                if not _df_best.empty:
                    _show_cols = [c for c in ['Symbol','Strategy','Timeframe','ROI_Per_Day_Pct','ROI_Annual_Percent',
                                               'Gross_Drawdown_Percent','Net_Drawdown_Percent','Win_Rate_Percent','Sharpe_Ratio',
                                               'Reality Score','Total_Trades','Webhook_Ready'] if c in _df_best.columns]
                    st.dataframe(_df_best[_show_cols].reset_index(drop=True),
                                 use_container_width=True, hide_index=True)

                if not _df_all.empty:
                    with st.expander("All Backtest Results"):
                        _show_all_cols = [c for c in ['Rank','Symbol','Strategy','Timeframe','ROI_Per_Day_Pct',
                                                       'Reality Score','OOS ROI %','WF Pass Rate %',
                                                       'Gross_Drawdown_Percent','Net_Drawdown_Percent','Win_Rate_Percent',
                                                       'Sharpe_Ratio','Alpha_Qualified','Deployment_Status'] if c in _df_all.columns]
                        st.dataframe(_df_all[_show_all_cols], use_container_width=True, hide_index=True)
            else:
                st.info("No alpha strategies qualified in the latest run. The full backtest results are saved below, but none met ROI/day > 1% with both drawdowns under 20%.")
                if not _df_all.empty:
                    with st.expander("All Backtest Results"):
                        _show_all_cols = [c for c in ['Rank','Symbol','Strategy','Timeframe','ROI_Per_Day_Pct',
                                                       'Reality Score','OOS ROI %','WF Pass Rate %',
                                                       'Gross_Drawdown_Percent','Net_Drawdown_Percent','Win_Rate_Percent',
                                                       'Sharpe_Ratio','Alpha_Qualified','Deployment_Status'] if c in _df_all.columns]
                        st.dataframe(_df_all[_show_all_cols], use_container_width=True, hide_index=True)


# ------------------------------------------------------------------------------
elif st.session_state.page == "Lighter":

    st.markdown('<div class="sec-title">Lighter DEX — Exchange Dashboard</div>', unsafe_allow_html=True)

    # -- Fetch live data from Lighter client -----------------------------------
    _lc = lighter_client

    # Connection status
    _lt_ready     = False
    _lt_can_trade = False
    _lt_balance   = 0.0
    _lt_account   = {}
    _lt_positions = []
    _lt_markets   = []
    _lt_prices    = {}
    _lt_error     = None

    if _lc is None:
        _lt_error = "LighterClient failed to initialise — check LIGHTER_* env vars"
    else:
        try:
            _lt_ready     = _lc.is_ready
            _lt_can_trade = _lc.can_trade
            _lt_balance   = _lc.get_account_balance() or 0.0
            _lt_account   = _lc.get_account_info()   or {}
            _lt_positions = _lt_account.get("positions", [])
            _lt_markets   = _lc.get_supported_markets() or []
            for _mkt in _lt_markets:
                try:
                    _lt_prices[_mkt] = _lc.get_mark_price(f"{_mkt}USD")
                except:
                    _lt_prices[_mkt] = None
        except Exception as _ex:
            _lt_error = str(_ex)

    # -- Status banner ----------------------------------------------------------
    if _lt_error:
        st.error(f"? Lighter connection error: {_lt_error}")
    else:
        _conn_color  = "#3fb950" if _lt_ready     else "#f85149"
        _trade_color = "#3fb950" if _lt_can_trade else "#d29922"
        _conn_label  = "? CONNECTED"  if _lt_ready     else "? OFFLINE"
        _trade_label = "? TRADES ON"  if _lt_can_trade else "? PAPER / READ-ONLY"
        _network     = "MAINNET" if os.getenv("LIGHTER_API_URL","").find("testnet") == -1 else "TESTNET"
        st.markdown(f"""
        <div style="display:flex;gap:12px;align-items:center;padding:10px 16px;
                    background:#161b27;border:1px solid #30363d;border-radius:10px;
                    margin-bottom:16px;flex-wrap:wrap">
          <span style="color:{_conn_color};font-weight:700;font-size:13px">{_conn_label}</span>
          <span style="color:#30363d">¦</span>
          <span style="color:{_trade_color};font-weight:700;font-size:13px">{_trade_label}</span>
          <span style="color:#30363d">¦</span>
          <span style="color:#58a6ff;font-size:12px;font-weight:600">Network: {_network}</span>
          <span style="color:#30363d">¦</span>
          <span style="color:#8b949e;font-size:12px">
            Lighter DEX · Perpetuals · Account #{_lt_account.get("account_index","—")}
          </span>
        </div>""", unsafe_allow_html=True)

    # -- Metric Cards ----------------------------------------------------------
    if not _lt_error:
        _open_count  = len([p for p in _lt_positions if abs(float(p.get("size", p.get("quantity", 0)))) > 0])
        _avail_bal   = _lt_account.get("available_balance", _lt_balance)
        _upnl_total  = sum(float(p.get("unrealized_pnl", p.get("uPnL", 0))) for p in _lt_positions)

        lm1, lm2, lm3, lm4 = st.columns(4)
        with lm1:
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#1f6feb,#388bfd)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Account Balance</div>
              <div class="dk-card-value" style="color:#58a6ff">${_lt_balance:,.2f}</div>
              <div class="dk-card-sub">Available: ${_avail_bal:,.2f}<br>Lighter Perpetuals</div>
            </div>""", unsafe_allow_html=True)
        with lm2:
            _upnl_col = "#3fb950" if _upnl_total >= 0 else "#f85149"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#3fb950,#56d364)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Unrealised PnL</div>
              <div class="dk-card-value" style="color:{_upnl_col}">${_upnl_total:+,.4f}</div>
              <div class="dk-card-sub">{_open_count} open position(s)</div>
            </div>""", unsafe_allow_html=True)
        with lm3:
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#bc8cff,#a371f7)"></div>
              <div class="dk-card-icon">??</div>
              <div class="dk-card-label">Markets Available</div>
              <div class="dk-card-value" style="color:#bc8cff">{len(_lt_markets)}</div>
              <div class="dk-card-sub">{", ".join(_lt_markets) if _lt_markets else "—"}</div>
            </div>""", unsafe_allow_html=True)
        with lm4:
            _tc_col = "#3fb950" if _lt_can_trade else "#d29922"
            _tc_lbl = "LIVE" if _lt_can_trade else "READ-ONLY"
            st.markdown(f"""
            <div class="dk-card">
              <div class="dk-card-accent" style="background:linear-gradient(90deg,#d29922,#e3b341)"></div>
              <div class="dk-card-icon">?</div>
              <div class="dk-card-label">Trade Mode</div>
              <div class="dk-card-value" style="color:{_tc_col}">{_tc_lbl}</div>
              <div class="dk-card-sub">LIGHTER_ALLOW_REAL_TRADES<br>
                = {os.getenv("LIGHTER_ALLOW_REAL_TRADES","false")}</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # -- Open Positions -----------------------------------------------------
        st.markdown('<div class="sec-title" style="font-size:14px">Open Positions</div>',
                    unsafe_allow_html=True)
        if _lt_positions:
            _pos_rows = []
            for _p in _lt_positions:
                _qty  = float(_p.get("size", _p.get("quantity", 0)))
                if abs(_qty) < 1e-9:
                    continue
                _sym  = _p.get("market", _p.get("symbol", "?"))
                _ep   = float(_p.get("entry_price", _p.get("avg_price", 0)))
                _upnl = float(_p.get("unrealized_pnl", _p.get("uPnL", 0)))
                _side = "LONG" if _qty > 0 else "SHORT"
                _pos_rows.append({
                    "Market":       _sym,
                    "Side":         _side,
                    "Size":         f"{abs(_qty):.6f}",
                    "Entry Price":  f"${_ep:,.4f}",
                    "Mark Price":   f"${_lt_prices.get(_sym, 0) or 0:,.4f}",
                    "Unrealised PnL": f"${_upnl:+.4f}",
                })
            if _pos_rows:
                st.dataframe(pd.DataFrame(_pos_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No open positions on Lighter.")
        else:
            st.info("No open positions on Lighter.")

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # -- Market Prices ------------------------------------------------------
        st.markdown('<div class="sec-title" style="font-size:14px">Live Market Prices</div>',
                    unsafe_allow_html=True)
        if _lt_markets:
            _mkt_cols = st.columns(len(_lt_markets))
            for _i, _mkt in enumerate(_lt_markets):
                _px = _lt_prices.get(_mkt)
                _px_str = f"${_px:,.2f}" if _px else "—"
                with _mkt_cols[_i]:
                    st.markdown(f"""
                    <div class="dk-card" style="text-align:center">
                      <div class="dk-card-label">{_mkt}/USD</div>
                      <div style="font-size:20px;font-weight:800;color:#58a6ff">{_px_str}</div>
                      <div class="dk-card-sub">Lighter Mark Price</div>
                    </div>""", unsafe_allow_html=True)
        else:
            st.info("No markets returned from Lighter client.")

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

        # -- Account Assets -----------------------------------------------------
        _lt_assets = _lt_account.get("assets", [])
        if _lt_assets:
            st.markdown('<div class="sec-title" style="font-size:14px">Account Assets</div>',
                        unsafe_allow_html=True)
            _asset_rows = []
            for _a in _lt_assets:
                _asset_rows.append({
                    "Asset":    _a.get("symbol", _a.get("asset", "?")),
                    "Balance":  f"{float(_a.get('balance', _a.get('qty', 0))):,.6f}",
                })
            st.dataframe(pd.DataFrame(_asset_rows), use_container_width=True, hide_index=True)

        # -- Trade Enable Toggle ------------------------------------------------
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown('<div class="sec-title" style="font-size:14px">Trade Settings</div>',
                    unsafe_allow_html=True)
        st.markdown(f"""
        <div class="dk-card">
          <div class="dk-card-label">Enable Live Trades</div>
          <div style="font-size:12px;color:#8b949e;margin-bottom:10px">
            Current: <b style="color:{'#3fb950' if _lt_can_trade else '#d29922'}">
              LIGHTER_ALLOW_REAL_TRADES = {os.getenv("LIGHTER_ALLOW_REAL_TRADES","false")}
            </b>
          </div>
          <div style="font-size:12px;color:#6e7681">
            To enable live trading on Lighter, set the environment variable in
            <code>/etc/tradingbot/env_vars</code>:<br><br>
            <code style="background:#0d1117;padding:4px 8px;border-radius:4px;color:#3fb950">
              LIGHTER_ALLOW_REAL_TRADES=true
            </code><br><br>
            Then restart the trading_orchestrator service.
          </div>
        </div>""", unsafe_allow_html=True)

        # -- Raw Account Debug --------------------------------------------------
        with st.expander("Raw Account Info (debug)"):
            st.json(_lt_account)

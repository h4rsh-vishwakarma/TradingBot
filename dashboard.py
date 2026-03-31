"""
Trading Bot — Senior Dashboard
Full visibility: Services · Exchanges · Algos · Trades · PnL · Safety · Signals · System
"""
import csv, gc, json, os, re, shutil, subprocess, sys, time
from collections import deque, defaultdict
from datetime import datetime, timezone, date
from pathlib import Path

import pandas as pd
import psutil
import streamlit as st

# ── paths ──────────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent
STORAGE       = PROJECT_ROOT / "tradingview_webhook_bot" / "storage"
LEDGER_PATH   = STORAGE / "ledger_state.json"
CB_PATH       = STORAGE / "circuit_breaker_state.json"
SIGNALS_PATH  = STORAGE / "signals.jsonl"
TOURNAMENT    = PROJECT_ROOT / "storage/reports/tournament_winners.csv"
ENV_FILE      = Path("/etc/tradingbot/env_vars")
SYSTEMCTL     = shutil.which("systemctl") or "/usr/bin/systemctl"
JOURNALCTL    = shutil.which("journalctl") or "/usr/bin/journalctl"

if str(PROJECT_ROOT / "tradingview_webhook_bot") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tradingview_webhook_bot"))

# ── helpers ────────────────────────────────────────────────────────────────
def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except Exception:
        return None

def svc_active(name):
    r = run([SYSTEMCTL, "is-active", name])
    return r and r.stdout.strip() == "active"

def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"')
    return env

def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}

def clean_tier(t):
    t = re.sub(r"[^\w\s\+\-]", "", str(t or "")).strip().upper()
    if "ALPHA" in t and "++" in t:  return "ALPHA++"
    if t in ("ALPHA",):             return "ALPHA"
    if t in ("AVERAGE", "SUB-ALPHA", "SUB ALPHA"): return "AVERAGE"
    if t in ("REJECT", "BLOCKED"):  return "REJECT"
    return t

def tail_lines(path, n=200):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return list(deque(f, maxlen=n))
    except Exception:
        return []

def journal(service, n=50):
    r = run([JOURNALCTL, "-u", service, "-n", str(n), "--no-pager"])
    return r.stdout if r else ""

# ── data loaders ───────────────────────────────────────────────────────────
@st.cache_data(ttl=15)
def load_ledger():
    return load_json(LEDGER_PATH)

@st.cache_data(ttl=15)
def load_circuit_breaker():
    return load_json(CB_PATH)

@st.cache_data(ttl=30)
def load_tournament():
    if not TOURNAMENT.exists():
        return []
    with open(TOURNAMENT) as f:
        return list(csv.DictReader(f))

@st.cache_data(ttl=10)
def load_signals(n=100):
    lines = tail_lines(SIGNALS_PATH, n)
    records = []
    for line in lines:
        try:
            d = json.loads(line)
            p = d.get("payload", d)
            records.append({
                "time":     d.get("timestamp", "")[:19],
                "symbol":   p.get("symbol", "?"),
                "action":   p.get("action", "?"),
                "price":    float(p.get("price", 0) or 0),
                "qty":      float(p.get("quantity", 0) or 0),
                "strategy": p.get("strategy", "unknown"),
                "exchange": p.get("exchange", "binance"),
            })
        except Exception:
            pass
    return records

@st.cache_data(ttl=10)
def load_journal_events(n=150):
    log = journal("trading_orchestrator", n)
    events = []
    keywords = ["SUCCESS", "BLOCKED", "FAILED", "AI Blocked", "sanity FAIL",
                "Circuit", "circuit", "Trade Executed", "Price sanity", "⚠️",
                "Heartbeat", "ERROR", "fill price", "Equity sizing"]
    for line in log.splitlines():
        if any(k in line for k in keywords):
            # Extract timestamp and message
            parts = line.split(" - ", 3)
            ts  = parts[0].split()[-1] if parts else ""
            msg = parts[-1][:120] if parts else line[:120]
            level = "INFO"
            if "ERROR" in line or "FAILED" in line or "sanity FAIL" in line:
                level = "ERROR"
            elif "WARNING" in line or "BLOCKED" in line or "⚠️" in line:
                level = "WARN"
            elif "SUCCESS" in line or "Trade Executed" in line:
                level = "SUCCESS"
            events.append({"ts": ts, "level": level, "msg": msg})
    return events[-30:]

@st.cache_data(ttl=10)
def get_live_prices():
    prices = {}
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "tradingview_webhook_bot"))
        from exchange.binance_client import BinanceClient
        c = BinanceClient()
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "LINKUSDT"]:
            try:
                p = c.get_mainnet_mark_price(sym)
                if p:
                    prices[sym] = p
            except Exception:
                pass
    except Exception:
        pass
    return prices

# ══════════════════════════════════════════════════════════════════════════
# MAIN DASHBOARD
# ══════════════════════════════════════════════════════════════════════════
def render():
    env = load_env()
    st.set_page_config(
        page_title="Trading Bot — Command Center",
        layout="wide",
        page_icon="🤖",
        initial_sidebar_state="collapsed"
    )

    # ── Header ──────────────────────────────────────────────────────────
    st.markdown("""
        <h1 style='text-align:center; color:#00d4aa;'>🤖 Trading Bot — Command Center</h1>
        <p style='text-align:center; color:#888; margin-top:-10px;'>
            Real-time system health, algorithm performance & trade monitoring
        </p>
    """, unsafe_allow_html=True)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"🕐 Last updated: {now_utc}  |  Auto-refresh every 30s")
    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 1 — SERVICE STATUS
    # ══════════════════════════════════════════════════════════════════
    st.subheader("📡 Service Status")
    services = [
        ("trading_orchestrator", "Orchestrator",      "Signal processor & trade executor"),
        ("trading_webhook",      "Webhook Server",     "Receives TradingView alerts (port 5000)"),
        ("trading_telegram",     "Telegram Alerts",    "Sends trade notifications"),
        ("trading_dashboard",    "Dashboard",          "This Streamlit UI (port 8501)"),
    ]
    cols = st.columns(4)
    all_ok = True
    for i, (svc, label, desc) in enumerate(services):
        ok = svc_active(svc)
        if not ok:
            all_ok = False
        with cols[i]:
            status_color = "#00c853" if ok else "#f44336"
            status_text  = "✅ ACTIVE" if ok else "🔴 DOWN"
            st.markdown(f"""
                <div style='background:#1e1e2e; border-left:4px solid {status_color};
                            padding:12px; border-radius:6px; height:90px;'>
                    <b style='color:{status_color};'>{status_text}</b><br>
                    <b>{label}</b><br>
                    <small style='color:#888;'>{desc}</small>
                </div>
            """, unsafe_allow_html=True)

    if all_ok:
        st.success("✅ All 4 services running normally")
    else:
        st.error("🔴 One or more services are DOWN")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 2 — EXCHANGE CONNECTIONS + LIVE PRICES
    # ══════════════════════════════════════════════════════════════════
    st.subheader("🔗 Exchange Connections & Live Prices")
    ex_col, price_col = st.columns([1, 2])

    with ex_col:
        # Check from journal logs
        orch_log = journal("trading_orchestrator", 80)
        binance_ok  = "Connected to Binance Futures [TESTNET]" in orch_log
        lighter_ok  = "Connected to Lighter [TESTNET]" in orch_log
        hl_key      = env.get("HL_WALLET_ADDRESS", "")
        is_testnet  = env.get("BINANCE_TESTNET", "false").lower() == "true"
        allow_real  = env.get("ALLOW_REAL_TRADES", "false").lower() == "true"
        lighter_real = env.get("LIGHTER_ALLOW_REAL_TRADES", "false").lower() == "true"

        rows = [
            ("Binance Futures", "TESTNET" if is_testnet else "MAINNET",
             binance_ok, f"Real trades: {'ON' if allow_real else 'Paper'}"),
            ("Lighter DEX",     "TESTNET",
             lighter_ok, f"Real trades: {'ON' if lighter_real else 'Paper'}"),
            ("Hyperliquid",     "TESTNET",
             bool(hl_key),      "Configured via HL_WALLET_ADDRESS"),
        ]
        for exch, net, ok, note in rows:
            color = "#00c853" if ok else "#ff9800"
            icon  = "✅" if ok else "⚠️"
            st.markdown(f"""
                <div style='background:#1e1e2e; border-left:4px solid {color};
                            padding:10px; border-radius:6px; margin-bottom:8px;'>
                    {icon} <b>{exch}</b> <span style='color:{color};font-size:12px;'>[{net}]</span><br>
                    <small style='color:#aaa;'>{note}</small>
                </div>
            """, unsafe_allow_html=True)

    with price_col:
        st.markdown("**Live Market Prices (Mainnet)**")
        prices = get_live_prices()
        if prices:
            p_cols = st.columns(len(prices))
            for i, (sym, price) in enumerate(prices.items()):
                base = sym.replace("USDT", "")
                with p_cols[i]:
                    st.metric(base, f"${price:,.2f}")
        else:
            st.warning("Live prices unavailable — check Binance connectivity")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3 — ALGORITHM BRAIN
    # ══════════════════════════════════════════════════════════════════
    st.subheader("🧠 Algorithm Brain — Tournament Leaderboard")
    rows = load_tournament()

    if rows:
        def safe_f(v):
            try: return float(v or 0)
            except: return 0.0

        tiers = defaultdict(list)
        for r in rows:
            tiers[clean_tier(r.get("Tier", ""))].append(r)

        # IS→OOS Retention Banner
        alpha_pp_rows = tiers.get("ALPHA++", [])
        oos_vals = [safe_f(r.get("OOS_Daily_ROI_%")) for r in alpha_pp_rows if safe_f(r.get("OOS_Daily_ROI_%")) > 0]
        is_vals  = [safe_f(r.get("Daily_ROI_%"))     for r in alpha_pp_rows if safe_f(r.get("Daily_ROI_%")) > 0]
        avg_oos  = sum(oos_vals)/len(oos_vals) if oos_vals else 0
        avg_is   = sum(is_vals)/len(is_vals)   if is_vals  else 0
        retention = (avg_oos/avg_is*100) if avg_is > 0 else 0
        oos_gt25 = sum(1 for v in oos_vals if v > 0.25)
        oos_gt15 = sum(1 for v in oos_vals if v > 0.15)
        st.info(
            "📊 **IS→OOS Retention: %.1f%%** | "
            "Avg IS: %.3f%%/day → Avg OOS: %.3f%%/day | "
            "Top candidates (OOS>0.25%%): **%d** | OOS>0.15%%: **%d** | "
            "⚠️ Realistic live expectation: **0.20–0.27%%/day**"
            % (retention, avg_is, avg_oos, oos_gt25, oos_gt15)
        )

        t_cols = st.columns(4)
        tier_data = [
            ("ALPHA++", "#ffd700", "🏆", "OOS-validated top performers"),
            ("ALPHA",   "#00c853", "✅", "OOS 0.10–0.25%/day"),
            ("AVERAGE", "#ff9800", "⚠️", "OOS < 0.10% — watch only"),
            ("REJECT",  "#f44336", "🚫", "Overfit / no live edge"),
        ]
        for i, (tier, color, icon, desc) in enumerate(tier_data):
            count = len(tiers.get(tier, []))
            with t_cols[i]:
                st.markdown(
                    "<div style='background:#1e1e2e; border:2px solid %s;"
                    "padding:14px; border-radius:8px; text-align:center;'>"
                    "<div style='font-size:28px;'>%s</div>"
                    "<div style='color:%s; font-size:22px; font-weight:bold;'>%d</div>"
                    "<div style='font-weight:bold;'>%s</div>"
                    "<div style='color:#888; font-size:11px;'>%s</div></div>"
                    % (color, icon, color, count, tier, desc),
                    unsafe_allow_html=True
                )

        st.markdown("**Total evaluated: %d** | OOS-based tiers (overfit downgraded)" % len(rows))

        # Top Testnet Candidates (OOS > 0.25)
        top_cands = sorted([r for r in alpha_pp_rows if safe_f(r.get("OOS_Daily_ROI_%")) > 0.25],
                           key=lambda x: -safe_f(x.get("OOS_Daily_ROI_%")))
        if top_cands:
            with st.expander("🚀 TOP %d TESTNET CANDIDATES (OOS > 0.25%%/day)" % len(top_cands), expanded=True):
                st.success("These %d strategies are OOS-validated. Deploy on testnet for 2-4 weeks." % len(top_cands))
                df_top = []
                for r in top_cands:
                    oos = safe_f(r.get("OOS_Daily_ROI_%"))
                    is_ = safe_f(r.get("Daily_ROI_%"))
                    ret = oos/is_*100 if is_ > 0 else 0
                    df_top.append({
                        "Symbol":      r.get("Symbol","?"),
                        "Strategy":    r.get("Strategy","?")[:40],
                        "OOS ROI/day": "%.3f%%" % oos,
                        "IS ROI/day":  "%.3f%%" % is_,
                        "Retention":   "%.0f%%" % ret,
                        "Sharpe":      r.get("Sharpe_Ratio","?"),
                        "Win Rate":    str(r.get("Win_Rate_%","?")) + "%",
                        "GDD":         str(r.get("Gross_DD_%","?")) + "%",
                    })
                st.dataframe(pd.DataFrame(df_top), hide_index=True, use_container_width=True)

        # Full ALPHA++ sorted by OOS
        with st.expander("🏆 All %d ALPHA++ Strategies (sorted by OOS)" % len(alpha_pp_rows), expanded=False):
            alpha_sorted = sorted(alpha_pp_rows, key=lambda x: -safe_f(x.get("OOS_Daily_ROI_%")))
            df_rows2 = []
            for r in alpha_sorted:
                oos = safe_f(r.get("OOS_Daily_ROI_%"))
                is_ = safe_f(r.get("Daily_ROI_%"))
                df_rows2.append({
                    "Symbol":      r.get("Symbol","?"),
                    "Strategy":    r.get("Strategy","?")[:45],
                    "OOS ROI/day": "%.3f%%" % oos,
                    "IS ROI/day":  "%.3f%%" % is_,
                    "OOS Sharpe":  r.get("OOS_Sharpe","?"),
                    "Sharpe":      r.get("Sharpe_Ratio","?"),
                    "Win Rate":    str(r.get("Win_Rate_%","?")) + "%",
                    "GDD":         str(r.get("Gross_DD_%","?")) + "%",
                })
            st.dataframe(pd.DataFrame(df_rows2), hide_index=True, use_container_width=True)

        with st.expander("✅ ALPHA Strategies (%d — OOS 0.10–0.25%%/day)" % len(tiers.get("ALPHA",[]))):
            alpha_s = sorted(tiers.get("ALPHA",[]), key=lambda x: -safe_f(x.get("OOS_Daily_ROI_%")))
            df_a = []
            for r in alpha_s:
                df_a.append({
                    "Symbol":      r.get("Symbol","?"),
                    "Strategy":    r.get("Strategy","?")[:45],
                    "OOS ROI/day": "%.3f%%" % safe_f(r.get("OOS_Daily_ROI_%")),
                    "IS ROI/day":  "%.3f%%" % safe_f(r.get("Daily_ROI_%")),
                    "Win Rate":    str(r.get("Win_Rate_%","?")) + "%",
                    "GDD":         str(r.get("Gross_DD_%","?")) + "%",
                })
            st.dataframe(pd.DataFrame(df_a), hide_index=True, use_container_width=True)
    else:
        st.error("Tournament leaderboard not found")
    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 3.5 — TRADINGVIEW SETUP (Symbol + PineScript Viewer)
    # ══════════════════════════════════════════════════════════════════
    st.subheader("📡 TradingView Setup — Top Strategies per Symbol")

    STRATEGY_TV_NAMES = {
        "Aggressive_Entry":    "10 Aggressive Entry",
        "Full_Momentum":       "21 Full Momentum",
        "Ichimoku_Trend_Pro":  "22 Ichimoku Trend Pro",
        "Ichimoku_MACD_Pro":   "23 Ichimoku MACD Pro",
        "Keltner_Breakout":    "24 Keltner Breakout",
        "MACD_Breakout":       "07 MACD Breakout",
        "Hybrid_SMC":          "Hybrid SMC [MarkitTick]",
        "SMC_LuxAlgo_WH":      "SMC Strategy [LuxAlgo] + Webhook",
        "BB_Squeeze_Break":    "BB Squeeze Break",
        "ML_Lorentzian":       "ML Lorentzian Classification",
        "EMA_Break_Momentum":  "03 EMA Break Momentum",
        "VWAP_Break_Entry":    "VWAP Break Entry [Live Trading]",
    }

    WEBHOOK_SECRET_VAL = "squeeze_tradingview_cluster_2026_secure"
    WEBHOOK_URL_VAL    = "http://15.207.152.119/webhook/tradingview"

    def get_alert_msg(strat, sym):
        tv = STRATEGY_TV_NAMES.get(strat, strat.replace("_"," "))
        return (
            f"{tv} | {sym} - Webhook ({WEBHOOK_SECRET_VAL}): "
            "order {{strategy.order.action}} @ {{strategy.order.contracts}} "
            f"filled on BINANCE:{sym}.P. New strategy position is {{{{strategy.position_size}}}}"
        )

    tv_rows = load_tournament()
    if tv_rows:
        # Symbol filter
        all_syms = sorted(set(r.get("Symbol","") for r in tv_rows))
        priority_syms = ["FILUSDT","LDOUSDT","UNIUSDT","SOLUSDT","ETHUSDT","AVAXUSDT"]
        default_syms = [s for s in priority_syms if s in all_syms]

        sel_syms = st.multiselect(
            "🔍 Select symbols to view strategies:",
            options=all_syms,
            default=default_syms,
            help="Choose which symbols to show top strategies for"
        )
        min_oos_filter = st.slider("Minimum OOS ROI (%/day)", 0.05, 0.50, 0.20, 0.01)

        if sel_syms:
            for sym in sel_syms:
                sym_rows = [r for r in tv_rows
                            if r.get("Symbol") == sym
                            and r.get("Tier") in ("ALPHA++","ALPHA")
                            and safe_f(r.get("OOS_Daily_ROI_%")) >= min_oos_filter]
                sym_rows = sorted(sym_rows, key=lambda x: -safe_f(x.get("OOS_Daily_ROI_%")))

                if not sym_rows:
                    continue

                best_oos = safe_f(sym_rows[0].get("OOS_Daily_ROI_%")) if sym_rows else 0
                label = f"📊 {sym} — {len(sym_rows)} strategies  |  Best OOS: {best_oos:.3f}%/day"
                with st.expander(label, expanded=(sym in ["FILUSDT","LDOUSDT","UNIUSDT"])):
                    st.caption(f"**Webhook URL:** `{WEBHOOK_URL_VAL}`")
                    for r in sym_rows:
                        strat  = r.get("Strategy","?")
                        tier   = r.get("Tier","?")
                        oos    = safe_f(r.get("OOS_Daily_ROI_%"))
                        is_roi = safe_f(r.get("Daily_ROI_%"))
                        wr     = r.get("Win_Rate_%","?")
                        gdd    = r.get("Gross_DD_%","?")
                        oos_sh = r.get("OOS_Sharpe","?")
                        tv_nm  = STRATEGY_TV_NAMES.get(strat, strat.replace("_"," "))
                        alert  = get_alert_msg(strat, sym)
                        ret    = oos/is_roi*100 if is_roi > 0 else 0

                        tier_color = "🟢" if tier == "ALPHA++" else "🔵"
                        header = f"{tier_color} **{strat}** — OOS `{oos:.3f}%%/day` | IS `{is_roi:.3f}%%/day` | Ret `{ret:.0f}%%` | WR `{wr}%%` | GDD `{gdd}%%` | Sharpe `{oos_sh}`"

                        with st.expander(header, expanded=False):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown(f"**TradingView Script Name:**")
                                st.code(tv_nm, language=None)
                            with c2:
                                st.markdown(f"**Tier:** `{tier}`  |  **OOS Sharpe:** `{oos_sh}`")
                                st.markdown(f"**Win Rate:** `{wr}%%`  |  **GDD:** `{gdd}%%`")

                            st.markdown("**📋 TradingView Alert Message** — Copy this into TradingView Alert → Message box:")
                            st.code(alert, language=None)
                            st.caption("⚠️ In TradingView: Strategy Settings → Add Alert → paste above in Message field. Webhook URL goes in the URL field.")
        else:
            st.info("Select at least one symbol above to see strategies.")
    else:
        st.warning("Tournament data not loaded — run the tournament first.")
    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 4 — PnL & OPEN POSITIONS
    # ══════════════════════════════════════════════════════════════════
    st.subheader("💰 PnL Summary & Positions")
    ledger = load_ledger()
    positions = ledger.get("positions", {})

    today_str = date.today().strftime("%Y-%m-%d")
    total_pnl = sum(v.get("realized_pnl", 0) for v in positions.values())
    today_pnl = sum(v.get("daily_realized_pnl", 0) for v in positions.values()
                    if v.get("last_update_date", "") == today_str)

    open_pos   = {k:v for k,v in positions.items() if abs(v.get("quantity",0)) > 0 and v.get("avg_price",0) != 0}
    ghost_pos  = {k:v for k,v in positions.items() if abs(v.get("quantity",0)) > 0 and v.get("avg_price",0) == 0}

    pnl_c1, pnl_c2, pnl_c3, pnl_c4 = st.columns(4)
    with pnl_c1:
        color = "normal" if today_pnl >= 0 else "inverse"
        st.metric("Today PnL", f"${today_pnl:.4f}", delta=f"{'▲' if today_pnl>=0 else '▼'} {today_str}")
    with pnl_c2:
        st.metric("All-time PnL", f"${total_pnl:.4f}")
    with pnl_c3:
        st.metric("Open Positions", len(open_pos))
    with pnl_c4:
        if ghost_pos:
            st.metric("⚠️ Ghost Positions", len(ghost_pos), help="Corrupted entries from wrong-price bug — need ledger reset")
        else:
            st.metric("Ledger Health", "✅ Clean")

    # Ghost warning
    if ghost_pos:
        st.warning(f"""
        ⚠️ **{len(ghost_pos)} Ghost Position(s) detected** — these are corrupted ledger entries from the
        wrong-price bug on Mar 30. They are NOT real open trades.
        PnL shown above includes these fake losses. **Actual real-money risk = $0 (testnet).**
        """)

    # By symbol PnL
    by_sym = defaultdict(float)
    for v in positions.values():
        sym = v.get("symbol","").replace("binance:","").split(":")[0]
        by_sym[sym] += v.get("realized_pnl", 0)
    non_zero = {k:v for k,v in by_sym.items() if abs(v) > 0.01}

    if non_zero:
        sym_df = pd.DataFrame([
            {"Symbol": k, "All-time PnL ($)": round(v, 4),
             "Status": "🟢 Profit" if v >= 0 else "🔴 Loss"}
            for k,v in sorted(non_zero.items(), key=lambda x: x[1])
        ])
        st.dataframe(sym_df, hide_index=True, use_container_width=True)

    if open_pos:
        st.markdown("**Real Open Positions:**")
        pos_df = pd.DataFrame([
            {"Position": k, "Quantity": v["quantity"],
             "Avg Price": f"${v['avg_price']:.2f}", "Realized PnL": f"${v['realized_pnl']:.4f}"}
            for k,v in open_pos.items()
        ])
        st.dataframe(pos_df, hide_index=True, use_container_width=True)

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 5 — SAFETY SYSTEMS
    # ══════════════════════════════════════════════════════════════════
    st.subheader("🛡️ Safety Systems")
    cb = load_circuit_breaker()
    tripped = cb.get("tripped", False) or str(cb.get("status","")).upper() == "TRIPPED"

    s1, s2, s3, s4, s5, s6 = st.columns(6)
    with s1:
        cb_color = "#f44336" if tripped else "#00c853"
        st.markdown(f"""
            <div style='background:#1e1e2e; border-left:4px solid {cb_color};
                        padding:10px; border-radius:6px; text-align:center;'>
                <b>Circuit Breaker</b><br>
                <span style='color:{cb_color}; font-size:18px;'>
                    {'🔴 TRIPPED' if tripped else '✅ OK'}
                </span>
            </div>
        """, unsafe_allow_html=True)
    with s2:
        st.metric("Daily Loss Tracked", f"${cb.get('daily_loss',0):.4f}")
    with s3:
        st.metric("CB Limit", f"{env.get('CB_DAILY_LOSS_PCT','5')}%/day")
    with s4:
        st.metric("Stop-Loss", f"{env.get('STOP_LOSS_PCT','3')}% per trade")
    with s5:
        st.metric("Take-Profit", f"{env.get('TAKE_PROFIT_PCT','5')}% per trade")
    with s6:
        st.metric("Price Sanity Check", "✅ 80% threshold", help="Signals with price >80% off market are replaced with live price")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 6 — RECENT SIGNALS
    # ══════════════════════════════════════════════════════════════════
    st.subheader("📥 Recent TradingView Signals")
    signals = load_signals(50)
    if signals:
        sig_df = pd.DataFrame(signals[-20:])
        sig_df["price_flag"] = sig_df.apply(
            lambda r: "⚠️ BAD" if r["price"] > 10000 and r["symbol"] in ["SOLUSDT","LINKUSDT","ETHUSDT","BNBUSDT"] else "✅ OK",
            axis=1
        )
        sig_df = sig_df.rename(columns={
            "time": "Time", "symbol": "Symbol", "action": "Action",
            "price": "Signal Price", "qty": "Qty",
            "strategy": "Strategy", "exchange": "Exchange", "price_flag": "Price Check"
        })
        st.dataframe(sig_df, hide_index=True, use_container_width=True)

        bad = sum(1 for s in signals if s["price"] > 10000 and s["symbol"] in ["SOLUSDT","LINKUSDT","ETHUSDT","BNBUSDT"])
        if bad:
            st.warning(f"⚠️ {bad} signals had wrong prices (>$10k for altcoins). "
                       "Price sanity check is replacing these with live market prices. "
                       "Fix TradingView alert templates to use `{{close}}`.")
    else:
        st.info("No signals received yet")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 7 — TRADE ACTIVITY LOG
    # ══════════════════════════════════════════════════════════════════
    st.subheader("📊 Recent Trade Activity (from Orchestrator)")
    events = load_journal_events()
    if events:
        for e in reversed(events):
            color = {"ERROR": "#f44336", "WARN": "#ff9800",
                     "SUCCESS": "#00c853", "INFO": "#90caf9"}.get(e["level"], "#ccc")
            icon  = {"ERROR": "🔴", "WARN": "⚠️",
                     "SUCCESS": "🟢", "INFO": "ℹ️"}.get(e["level"], "•")
            st.markdown(f"""
                <div style='font-family:monospace; font-size:12px; color:{color};
                            margin:2px 0; padding:3px 6px; background:#1a1a2e; border-radius:3px;'>
                    {icon} <b>{e["ts"]}</b> — {e["msg"]}
                </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No trade events yet — bot is waiting for TradingView signals")

    st.divider()

    # ══════════════════════════════════════════════════════════════════
    # SECTION 8 — SYSTEM VITALS
    # ══════════════════════════════════════════════════════════════════
    st.subheader("🖥️ System Vitals")
    v1, v2, v3, v4, v5 = st.columns(5)
    cpu = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = datetime.fromtimestamp(psutil.boot_time())
    uptime_h  = (datetime.now() - boot_time).total_seconds() / 3600

    with v1:
        cpu_color = "#f44336" if cpu > 80 else "#00c853"
        st.metric("CPU Usage", f"{cpu:.1f}%")
    with v2:
        ram_pct = ram.percent
        st.metric("RAM Usage", f"{ram_pct:.1f}%", delta=f"{ram.used/1e9:.1f}GB used")
    with v3:
        st.metric("Disk Usage", f"{disk.percent:.1f}%", delta=f"{disk.free/1e9:.1f}GB free")
    with v4:
        st.metric("Server Uptime", f"{uptime_h:.1f}h")
    with v5:
        webhook_up = any(c.laddr.port == 5000 for c in psutil.net_connections() if c.status == "LISTEN")
        st.metric("Port 5000", "✅ OPEN" if webhook_up else "🔴 CLOSED")

    # ── Config summary ─────────────────────────────────────────────
    with st.expander("⚙️ Bot Configuration"):
        cfg_data = {
            "Binance Mode":        "TESTNET" if env.get("BINANCE_TESTNET","true")=="true" else "MAINNET",
            "Allow Real Trades":   env.get("ALLOW_REAL_TRADES", "?"),
            "Position Size Mode":  env.get("POSITION_SIZE_MODE", "fixed"),
            "Leverage":            env.get("LEVERAGE", "1"),
            "Stop-Loss %":         env.get("STOP_LOSS_PCT", "3.0"),
            "Take-Profit %":       env.get("TAKE_PROFIT_PCT", "5.0"),
            "CB Daily Loss Limit": env.get("CB_DAILY_LOSS_PCT", "5.0") + "%",
            "CB Max Consec Losses":env.get("CB_MAX_CONSECUTIVE_LOSSES", "8"),
            "Cooldown (seconds)":  env.get("SYMBOL_COOLDOWN_SECONDS", "60"),
            "Dedup Window (sec)":  env.get("DEDUP_WINDOW_SECONDS", "120"),
            "Max Notional/trade":  "$" + env.get("MAX_NOTIONAL_PER_TRADE", "500"),
            "Lighter Real Trades": env.get("LIGHTER_ALLOW_REAL_TRADES", "false"),
            "Lighter Network":     "TESTNET" if "testnet" in env.get("LIGHTER_API_URL","").lower() else "MAINNET",
            "Allowed Symbols":     env.get("ALLOWED_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT"),
        }
        cfg_df = pd.DataFrame(
            [{"Parameter": k, "Value": v} for k, v in cfg_data.items()]
        )
        st.dataframe(cfg_df, hide_index=True, use_container_width=True)

    # ── Footer ─────────────────────────────────────────────────────
    st.divider()
    st.markdown("""
        <div style='text-align:center; color:#555; font-size:12px;'>
            🤖 Trading Bot v2.0 · Binance Testnet · Lighter Testnet · Hyperliquid Testnet<br>
            Auto-refreshes every 30 seconds · All trades on TESTNET · No real money at risk
        </div>
    """, unsafe_allow_html=True)

    gc.collect()
    time.sleep(30)
    st.rerun()


if __name__ == "__main__":
    render()

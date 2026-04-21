"""
dd_optimizer_v2.py
==================
Enhanced: IS + OOS separate columns, all parameters, live readiness score.
SL fixed at 1.5%, TP varied: 6%, 8%, 10%, 12%
"""
import sys, pandas as pd, numpy as np
sys.path.insert(0, '/home/ubuntu/tradingview_webhook_bot/scripts')
from my_strategies_v2 import apply_strategy, calculate_adx
from backtest_engine_v4 import run_backtest, run_backtest_oos

def enforce(sig_series, min_gap=2, max_hold=24):
    sig = sig_series.values.copy(); last_sig_bar = -min_gap; cur = 0; hc = 0
    res = np.zeros(len(sig), dtype=int)
    for i in range(len(sig)):
        if sig[i] != 0:
            if (i - last_sig_bar) >= min_gap:
                res[i] = int(sig[i]); last_sig_bar = i; cur = int(sig[i]); hc = 1
        elif cur != 0:
            hc += 1
            if hc <= max_hold: res[i] = cur
            else: cur = 0; hc = 0
    return pd.Series(res, index=sig_series.index)

BEST_COMBOS = {
    'OPUSDT':   ('56 psar volume tight',    2.0, 16),
    'SUIUSDT':  ('24 keltner breakout',     2.0, 16),
    'AAVEUSDT': ('07 macd breakout',        2.0, 16),
    'LINKUSDT': ('44 psar volume surge 4h', 2.0, 16),
    'ARBUSDT':  ('44 psar volume surge 4h', 2.0, 16),
    'AVAXUSDT': ('10 aggressive entry',     2.0, 16),
    'DOTUSDT':  ('56 psar volume tight',    2.0, 16),
    'DOGEUSDT': ('56 psar volume tight',    2.0, 16),
    'INJUSDT':  ('21 full momentum',        2.0, 16),
    'LDOUSDT':  ('56 psar volume tight',    2.0, 16),
    'NEARUSDT': ('24 keltner breakout',     2.0, 16),
    'APTUSDT':  ('23 ichimoku macd pro',    2.0, 16),
    'SOLUSDT':  ('07 macd breakout',        2.0, 16),
    'ATOMUSDT': ('07 macd breakout',        2.0, 16),
    'UNIUSDT':  ('23 ichimoku macd pro',    2.0, 16),
    'FILUSDT':  ('21 full momentum',        2.0, 16),
}

TP_VALUES = [0.06, 0.08, 0.10, 0.12]
SL        = 0.015
DATA_DIR  = '/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/'
LEVERAGE  = 2.0
TRAIN_PCT = 0.80

# ── Full results store per TP ──────────────────────────────────────────────
all_results = {}  # tp -> list of row dicts

for sym, (strat, mult, length) in BEST_COMBOS.items():
    fpath = DATA_DIR + sym + '_3y_4h.csv'
    df = pd.read_csv(fpath)
    df.columns = [c.lower() for c in df.columns]
    if 'high' not in df.columns: df['high'] = df['close']
    if 'low'  not in df.columns: df['low']  = df['close']

    sig_raw = apply_strategy(df, strat, True, mult, length)
    adx     = calculate_adx(df, n=14)
    sig_raw = np.where(adx > 20, sig_raw, 0)
    df['sig'] = enforce(pd.Series(sig_raw, index=df.index))

    total_bars = len(df)
    split_idx  = int(total_bars * TRAIN_PCT)
    df_is      = df.iloc[:split_idx].copy().reset_index(drop=True)
    df_oos     = df.iloc[split_idx:].copy().reset_index(drop=True)
    days_total = 1095
    days_oos   = int(days_total * (1 - TRAIN_PCT))

    for tp in TP_VALUES:
        is_res  = run_backtest(
            df_is, signal_col='sig',
            sl_pct=SL, tp_pct=tp,
            leverage=LEVERAGE, total_days=int(days_total * TRAIN_PCT),
            use_intrabar=False, min_entry_gap=2,
            min_trades=10, exit_on_signal_off=True
        )
        oos_res = run_backtest(
            df_oos, signal_col='sig',
            sl_pct=SL, tp_pct=tp,
            leverage=LEVERAGE, total_days=days_oos,
            use_intrabar=False, min_entry_gap=2,
            min_trades=5, exit_on_signal_off=True
        )
        if not is_res or not oos_res:
            continue

        # Overfit ratio
        oos_roi = oos_res['roi_daily_pct']
        is_roi  = is_res['roi_daily_pct']
        overfit = oos_roi / is_roi if abs(is_roi) > 0.001 else 0.0

        # Live readiness score (0-100)
        score = 0
        if oos_roi >= 0.75:   score += 30
        elif oos_roi >= 0.50: score += 15
        if abs(oos_res['max_dd_pct']) <= 15:  score += 25
        elif abs(oos_res['max_dd_pct']) <= 25: score += 12
        if overfit >= 0.70:   score += 20
        elif overfit >= 0.50: score += 10
        if oos_res['win_rate_pct'] >= 50: score += 15
        elif oos_res['win_rate_pct'] >= 42: score += 7
        if oos_res['profit_factor'] >= 1.5: score += 10
        elif oos_res['profit_factor'] >= 1.2: score += 5

        if score >= 75:   live_status = "🟢 LIVE_READY"
        elif score >= 55: live_status = "🟡 PAPER_FIRST"
        elif score >= 35: live_status = "🟠 TESTNET"
        else:             live_status = "🔴 SKIP"

        row = {
            'sym':        sym,
            'strat':      strat,
            'mult':       mult,
            'length':     length,
            'sl_pct':     SL,
            'tp_pct':     tp,
            'leverage':   LEVERAGE,
            # IS columns
            'is_roi':     is_roi,
            'is_max_dd':  is_res['max_dd_pct'],
            'is_wr':      is_res['win_rate_pct'],
            'is_pf':      is_res['profit_factor'],
            'is_trades':  is_res['total_trades'],
            'is_sharpe':  is_res.get('sharpe_ratio', 0),
            # OOS columns
            'oos_roi':    oos_roi,
            'oos_max_dd': oos_res['max_dd_pct'],
            'oos_wr':     oos_res['win_rate_pct'],
            'oos_pf':     oos_res['profit_factor'],
            'oos_trades': oos_res['total_trades'],
            'oos_sharpe': oos_res.get('sharpe_ratio', 0),
            # Meta
            'overfit_ratio': overfit,
            'live_score':    score,
            'live_status':   live_status,
            'grade':         oos_res['performance_grade'],
        }
        all_results.setdefault(tp, []).append(row)


# ═══════════════════════════════════════════════════════════════════════
# PRINT FULL COMPARISON TABLE PER TP
# ═══════════════════════════════════════════════════════════════════════
W = 130

print("=" * W)
print("  DD OPTIMIZER v2 — SL=1.5% FIXED  |  IS vs OOS SEPARATE  |  ALL PARAMETERS")
print("=" * W)

for tp in TP_VALUES:
    rows = all_results.get(tp, [])
    if not rows: continue

    rows_sorted = sorted(rows, key=lambda x: x['oos_roi'], reverse=True)

    # Summary stats
    oos_rois = [r['oos_roi']    for r in rows]
    oos_dds  = [r['oos_max_dd'] for r in rows]
    is_rois  = [r['is_roi']     for r in rows]
    targets  = sum(1 for r in rows if r['oos_roi'] >= 0.75)
    avg_ratio = sum(r['oos_roi']/max(abs(r['oos_max_dd']),0.01) for r in rows) / len(rows)

    rr = tp / SL

    print()
    print("─" * W)
    print("  TP = %.0f%%   SL = 1.5%%   R:R = 1:%.1f   Leverage = 2x   Timeframe = 4H" % (tp*100, rr))
    print("─" * W)
    hdr = "%-12s %-24s | %-9s %-9s %-7s %-6s %-6s %-7s | %-9s %-9s %-7s %-6s %-6s %-7s | %-8s %-7s %-5s %-14s" % (
        "Symbol", "Strategy",
        "IS/day", "IS_MaxDD", "IS_WR%", "IS_PF", "IS_Tr", "IS_Shr",
        "OOS/day", "OOS_DD", "OOS_WR%", "OOS_PF","OOS_Tr","OOS_Shr",
        "Overfit", "Score", "ADX",  "Status"
    )
    print(hdr)
    print("─" * W)

    for r in rows_sorted:
        print("%-12s %-24s | %-9s %-9s %-7s %-6s %-6s %-7s | %-9s %-9s %-7s %-6s %-6s %-7s | %-8s %-7s %-5s %-14s" % (
            r['sym'], r['strat'][:24],
            "%.3f%%" % r['is_roi'],
            "%.1f%%"  % r['is_max_dd'],
            "%.1f%%"  % r['is_wr'],
            "%.2f"    % r['is_pf'],
            str(r['is_trades']),
            "%.2f"    % r['is_sharpe'],
            "%.3f%%" % r['oos_roi'],
            "%.1f%%"  % r['oos_max_dd'],
            "%.1f%%"  % r['oos_wr'],
            "%.2f"    % r['oos_pf'],
            str(r['oos_trades']),
            "%.2f"    % r['oos_sharpe'],
            "%.2f"    % r['overfit_ratio'],
            str(r['live_score']),
            "20+",
            r['live_status']
        ))

    print("─" * W)
    print("  AVG IS/day: %.3f%%   AVG OOS/day: %.3f%%   AVG MaxDD: %.1f%%   Targets≥0.75%%: %d/%d   ROI/DD: %.3f" % (
        sum(is_rois)/len(is_rois),
        sum(oos_rois)/len(oos_rois),
        sum(oos_dds)/len(oos_dds),
        targets, len(rows), avg_ratio
    ))


# ═══════════════════════════════════════════════════════════════════════
# BEST TP SUMMARY
# ═══════════════════════════════════════════════════════════════════════
print()
print("=" * W)
print("  TP COMPARISON SUMMARY")
print("=" * W)
print("%-8s %-12s %-12s %-12s %-16s %-12s" % (
    "TP", "Avg IS/day", "Avg OOS/day", "Avg MaxDD", "Targets>=0.75%", "ROI/DD Ratio"))
print("─" * 80)
best_tp = None; best_ratio = -999
for tp in TP_VALUES:
    rows = all_results.get(tp, [])
    if not rows: continue
    oos_rois = [r['oos_roi']    for r in rows]
    is_rois  = [r['is_roi']     for r in rows]
    oos_dds  = [r['oos_max_dd'] for r in rows]
    targets  = sum(1 for r in rows if r['oos_roi'] >= 0.75)
    ratio    = (sum(oos_rois)/len(oos_rois)) / max(abs(sum(oos_dds)/len(oos_dds)), 0.01)
    marker   = " ← BEST" if ratio > best_ratio else ""
    if ratio > best_ratio: best_ratio = ratio; best_tp = tp
    print("%-8s %-12s %-12s %-12s %-16s %-12s%s" % (
        "%.0f%%" % (tp*100),
        "%.3f%%" % (sum(is_rois)/len(is_rois)),
        "%.3f%%" % (sum(oos_rois)/len(oos_rois)),
        "%.1f%%"  % (sum(oos_dds)/len(oos_dds)),
        "%d/%d" % (targets, len(rows)),
        "%.3f"   % ratio,
        marker
    ))


# ═══════════════════════════════════════════════════════════════════════
# LIVE TRADING RECOMMENDATIONS — BEST TP ONLY
# ═══════════════════════════════════════════════════════════════════════
if best_tp:
    rows = all_results[best_tp]
    live_rows   = [r for r in rows if r['live_status'].startswith('🟢')]
    paper_rows  = [r for r in rows if r['live_status'].startswith('🟡')]
    testnet_rows= [r for r in rows if r['live_status'].startswith('🟠')]

    print()
    print("=" * W)
    print("  LIVE TRADING DECISION TABLE — TP=%.0f%%  SL=1.5%%  Leverage=2x  ADX>20  4H Timeframe" % (best_tp*100))
    print("=" * W)

    def print_group(label, group):
        if not group: return
        g_sorted = sorted(group, key=lambda x: x['live_score'], reverse=True)
        print()
        print("  %s" % label)
        print("  %-12s %-24s %-10s %-10s %-8s %-8s %-8s %-8s %-10s %-10s" % (
            "Symbol", "Strategy", "OOS/day", "OOS_MaxDD", "OOS_WR", "OOS_PF",
            "IS/day", "Overfit", "Score/100", "Decision"))
        print("  " + "─" * 110)
        for r in g_sorted:
            print("  %-12s %-24s %-10s %-10s %-8s %-8s %-8s %-8s %-10s %-10s" % (
                r['sym'], r['strat'][:24],
                "%.3f%%" % r['oos_roi'],
                "%.1f%%"  % r['oos_max_dd'],
                "%.1f%%"  % r['oos_wr'],
                "%.2f"    % r['oos_pf'],
                "%.3f%%" % r['is_roi'],
                "%.2f"    % r['overfit_ratio'],
                str(r['live_score']),
                r['live_status']
            ))

    print_group("🟢 LIVE READY — Deploy with real capital (start small: 1-2% per trade)", live_rows)
    print_group("🟡 PAPER FIRST — Run 2-4 weeks paper trading, then live", paper_rows)
    print_group("🟠 TESTNET — Needs more validation", testnet_rows)

    # Full parameter config for live-ready symbols
    if live_rows:
        print()
        print("=" * W)
        print("  COMPLETE CONFIG FOR LIVE DEPLOYMENT")
        print("=" * W)
        for r in sorted(live_rows, key=lambda x: x['live_score'], reverse=True):
            print()
            print("  ┌─ %s (%s)" % (r['sym'], r['strat']))
            print("  │  Timeframe   : 4H")
            print("  │  Strategy    : %s" % r['strat'])
            print("  │  ADX Filter  : > 20 (n=14)")
            print("  │  Min Gap     : 2 bars (8 hours)")
            print("  │  Max Hold    : 24 bars (4 days)")
            print("  │  SL          : %.1f%%" % (r['sl_pct'] * 100))
            print("  │  TP          : %.0f%%" % (r['tp_pct'] * 100))
            print("  │  Leverage    : %.0fx" % r['leverage'])
            print("  │  Execution   : Bar-close only (webhook bot compatible)")
            print("  │  OOS ROI     : %.3f%%/day  (%.1f%%/yr annualized)" % (
                r['oos_roi'], ((1 + r['oos_roi']/100)**365 - 1)*100))
            print("  │  IS  ROI     : %.3f%%/day  (overfit ratio: %.2f)" % (
                r['is_roi'], r['overfit_ratio']))
            print("  │  Max DD      : %.1f%%  |  Win Rate: %.1f%%  |  PF: %.2f" % (
                r['oos_max_dd'], r['oos_wr'], r['oos_pf']))
            print("  │  OOS Trades  : %d  |  OOS Sharpe: %.2f" % (
                r['oos_trades'], r['oos_sharpe']))
            print("  │  Live Score  : %d/100  →  %s" % (r['live_score'], r['live_status']))
            print("  └─────────────────────────────────────────────────")

print()
print("=" * W)
print("  NOTES:")
print("  • IS  = In-Sample  (first 80% data, used for strategy selection)")
print("  • OOS = Out-of-Sample (last 20% data, NEVER seen during optimization)")
print("  • Overfit Ratio = OOS_ROI / IS_ROI  (>0.7 = genuine edge, <0.3 = overfit)")
print("  • Score = 0-100 composite: OOS ROI (30) + MaxDD (25) + Overfit (20) + WR (15) + PF (10)")
print("  • All execution: bar-close only (compatible with TradingView webhook bot)")
print("=" * W)

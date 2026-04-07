"""
backtest_engine_v4.py
=====================
Unified Backtest Engine — best of TV Validator + tournament_4h_v3 + donchian_backtest

Fixes applied vs previous engines
───────────────────────────────────────────────────────────────────────────────
 PROBLEM                         OLD                    NEW (v4)
 ─────────────────────────────── ────────────────────── ──────────────────────
 ROI formula                     total_return / days    CAGR per-day
 SL/TP execution                 close price only       Intrabar High/Low
 Commission                      0 (tournament) /       0.06% per side
                                  0.1% (donchian)        (same as TV default)
 Position sizing                 100% compound /        95% equity per trade
                                  no sizing              (Pine default_qty=95)
 Win rate basis                  per-bar (tournament)   per trade (entry→exit)
 Sharpe basis                    per-bar √2190           daily P&L √252
 Drawdown types                  1–2 types              4 types (Max/Gross/Net/
                                                         Current) — TV compat
 Grading                         custom tiers           TV Validator tiers
 Re-entry after SL               immediate              blocked N bars (gap)
───────────────────────────────────────────────────────────────────────────────
"""

import pandas as pd
import numpy as np
from math import sqrt
from typing import Optional

# ── Defaults (match TradingView + Pine Script defaults) ──────────────────────
COMMISSION_PER_SIDE = 0.0006   # 0.06% futures taker  (TV: commission=0.06)
POSITION_SIZE_PCT   = 0.95     # 95% equity per trade  (Pine: default_qty=95)
INITIAL_CAPITAL     = 10_000
LEVERAGE_DEFAULT    = 2.0
TOTAL_DAYS          = 1095     # 3-year backtest window

# ── Grading Tiers ────────────────────────────────────────────────────────────
# Uses MAX drawdown (peak-to-trough) not gross_dd.
# Reason: gross_dd accumulates ALL losses and penalises high-churn strategies
# (e.g. 1000 small losses = 1000% gross_dd even on a profitable strategy).
# Max DD is what traders actually monitor and is directly comparable to TV's
# "Max Drawdown" metric in the Strategy Performance tab.
#
# (grade, deploy_status, min_annual_roi%, max_max_dd%, min_win_rate%)
TIERS = [
    ("EXCEPTIONAL", "TIER_1_DEPLOY", 500, 35, 55),
    ("STRONG",      "TIER_1",        200, 50, 45),
    ("PROMISING",   "TIER_2",         50, 60, 40),
    ("TESTING",     "PAPER_TRADE",    15, 75, 35),
]


def run_backtest(
    df              : pd.DataFrame,
    signal_col      : str   = "sig",
    sl_pct          : float = 0.015,
    tp_pct          : float = 0.060,
    trail_pct       : float = 0.000,
    commission      : float = COMMISSION_PER_SIDE,
    leverage        : float = LEVERAGE_DEFAULT,
    position_size   : float = POSITION_SIZE_PCT,
    initial_capital : float = INITIAL_CAPITAL,
    total_days      : int   = TOTAL_DAYS,
    use_intrabar    : bool  = True,
    min_entry_gap   : int   = 0,
    min_trades      : int   = 10,
    exit_on_signal_off: bool = True,
) -> Optional[dict]:
    """
    Core trade-simulation backtest.

    Parameters
    ----------
    df            : DataFrame — must have: close, high, low, [timestamp], [signal_col]
    signal_col    : Column with trade signals (1=long, -1=short, 0=flat)
    sl_pct        : Stop-loss % from entry  (e.g. 0.015 = 1.5%)
    tp_pct        : Take-profit % from entry (e.g. 0.06 = 6%)
    trail_pct     : Trailing stop % from price (0 = disabled)
    commission    : Per-side fee as decimal (0.0006 = 0.06%)
    leverage      : Position leverage multiplier
    position_size : Fraction of equity allocated per trade (0.95 = 95%)
    total_days    : Backtest period in calendar days — used for CAGR
    use_intrabar  : Use High/Low for SL/TP (True = TV-equivalent accuracy)
    min_entry_gap      : Bars to wait after SL/TP exit before next entry
                         (use MIN_BAR_GAP from tournament to prevent rapid re-entry)
    min_trades         : Minimum trades for a valid result (returns None if fewer)
    exit_on_signal_off : If True (default), close position when signal turns 0.
                         Use True for tournament (MAX_HOLD expiry = exit).
                         Use False for entry-only strategies (Donchian, etc.)
                         where SL/TP/trail are the ONLY exits.

    Returns
    -------
    dict with all metrics, or None if < min_trades
    """
    if signal_col not in df.columns:
        return None

    close_arr = df["close"].values.astype(float)
    high_arr  = df["high"].values.astype(float) if (use_intrabar and "high" in df.columns) else close_arr
    low_arr   = df["low"].values.astype(float)  if (use_intrabar and "low"  in df.columns) else close_arr
    sig_arr   = df[signal_col].values.astype(int)
    n         = len(df)

    # Extract dates for daily Sharpe (TV Validator style)
    dates = None
    for col in ("timestamp", "time", "date", "open_time"):
        if col in df.columns:
            try:
                dates = pd.to_datetime(df[col]).dt.date.values
            except Exception:
                pass
            break

    # ── Simulation state ─────────────────────────────────────────────────────
    capital        = float(initial_capital)
    position       = 0          # 0=flat, 1=long, -1=short
    entry_price    = 0.0
    entry_bar      = -1
    trail_stop     = 0.0
    last_exit_bar  = -min_entry_gap - 1

    trades          = []         # (ret_pct, pnl_usd, entry_bar_idx, exit_bar_idx)
    equity_arr      = [capital]
    daily_pnl_map   = {}         # date → cumulative pnl_usd  (for Sharpe)

    # ── Main loop ────────────────────────────────────────────────────────────
    for i in range(1, n):
        price = close_arr[i]
        hi    = high_arr[i]
        lo    = low_arr[i]
        sig   = sig_arr[i]

        # ── EXIT MANAGEMENT ──────────────────────────────────────────────────
        if position != 0:
            exit_px = None

            if position == 1:
                # Ratchet trailing stop upward
                if trail_pct > 0.0:
                    cand = price * (1.0 - trail_pct)
                    if cand > trail_stop:
                        trail_stop = cand

                sl_lvl = entry_price * (1.0 - sl_pct)
                tp_lvl = entry_price * (1.0 + tp_pct)

                if use_intrabar:
                    # SL checked before TP (conservative — TV default)
                    if lo <= sl_lvl:
                        exit_px = sl_lvl
                    elif hi >= tp_lvl:
                        exit_px = tp_lvl
                    elif trail_pct > 0.0 and lo <= trail_stop:
                        exit_px = trail_stop
                    elif sig == -1:                   # reversal always exits
                        exit_px = price
                    elif sig == 0 and exit_on_signal_off:  # signal-off exit (tournament)
                        exit_px = price
                else:
                    if price <= sl_lvl:
                        exit_px = sl_lvl
                    elif price >= tp_lvl:
                        exit_px = tp_lvl
                    elif trail_pct > 0.0 and price <= trail_stop:
                        exit_px = trail_stop
                    elif sig == -1:
                        exit_px = price
                    elif sig == 0 and exit_on_signal_off:
                        exit_px = price

                if exit_px is not None:
                    ret_pct   = (exit_px - entry_price) / entry_price * leverage
                    pos_value = capital * position_size
                    # Commission both sides on position value
                    pnl_usd   = pos_value * ret_pct - pos_value * commission * 2.0
                    capital   = max(capital + pnl_usd, 0.01)
                    trades.append((ret_pct, pnl_usd, entry_bar, i))
                    if dates is not None:
                        d = dates[i]
                        daily_pnl_map[d] = daily_pnl_map.get(d, 0.0) + pnl_usd
                    position      = 0
                    last_exit_bar = i

            elif position == -1:
                # Ratchet trailing stop downward
                if trail_pct > 0.0:
                    cand = price * (1.0 + trail_pct)
                    if cand < trail_stop:
                        trail_stop = cand

                sl_lvl = entry_price * (1.0 + sl_pct)
                tp_lvl = entry_price * (1.0 - tp_pct)

                if use_intrabar:
                    if hi >= sl_lvl:
                        exit_px = sl_lvl
                    elif lo <= tp_lvl:
                        exit_px = tp_lvl
                    elif trail_pct > 0.0 and hi >= trail_stop:
                        exit_px = trail_stop
                    elif sig == 1:                         # reversal always exits
                        exit_px = price
                    elif sig == 0 and exit_on_signal_off:  # signal-off exit (tournament)
                        exit_px = price
                else:
                    if price >= sl_lvl:
                        exit_px = sl_lvl
                    elif price <= tp_lvl:
                        exit_px = tp_lvl
                    elif trail_pct > 0.0 and price >= trail_stop:
                        exit_px = trail_stop
                    elif sig == 1:
                        exit_px = price
                    elif sig == 0 and exit_on_signal_off:
                        exit_px = price

                if exit_px is not None:
                    ret_pct   = (entry_price - exit_px) / entry_price * leverage
                    pos_value = capital * position_size
                    pnl_usd   = pos_value * ret_pct - pos_value * commission * 2.0
                    capital   = max(capital + pnl_usd, 0.01)
                    trades.append((ret_pct, pnl_usd, entry_bar, i))
                    if dates is not None:
                        d = dates[i]
                        daily_pnl_map[d] = daily_pnl_map.get(d, 0.0) + pnl_usd
                    position      = 0
                    last_exit_bar = i

        # ── ENTRY MANAGEMENT ─────────────────────────────────────────────────
        if position == 0 and (i - last_exit_bar) > min_entry_gap:
            if sig == 1:
                position    = 1
                entry_price = price
                entry_bar   = i
                trail_stop  = price * (1.0 - trail_pct) if trail_pct > 0.0 else 0.0
            elif sig == -1:
                position    = -1
                entry_price = price
                entry_bar   = i
                trail_stop  = price * (1.0 + trail_pct) if trail_pct > 0.0 else 0.0

        equity_arr.append(capital)

    # Close any open position at end of data (at last close price)
    if position != 0 and entry_price > 0:
        price = close_arr[-1]
        if position == 1:
            ret_pct = (price - entry_price) / entry_price * leverage
        else:
            ret_pct = (entry_price - price) / entry_price * leverage
        pos_value = capital * position_size
        pnl_usd   = pos_value * ret_pct - pos_value * commission * 2.0
        capital   = max(capital + pnl_usd, 0.01)
        trades.append((ret_pct, pnl_usd, entry_bar, n - 1))
        equity_arr[-1] = capital

    # ── Guard: need enough trades ─────────────────────────────────────────────
    if len(trades) < min_trades:
        return None

    # ── METRICS ──────────────────────────────────────────────────────────────
    equity       = np.array(equity_arr, dtype=float)
    final_cap    = float(capital)
    net_profit   = final_cap - initial_capital
    total_return = net_profit / initial_capital * 100.0

    # 1. ROI — CAGR (TV Validator formula)
    ratio       = max(final_cap / initial_capital, 1e-9)
    cagr_daily  = (ratio ** (1.0 / total_days) - 1.0) * 100.0
    years       = total_days / 365.25
    roi_annual  = (ratio ** (1.0 / years) - 1.0) * 100.0

    # 2. Trade stats — per trade, not per bar
    total_t       = len(trades)
    pnl_arr       = np.array([t[1] for t in trades], dtype=float)
    ret_arr       = np.array([t[0] for t in trades], dtype=float)
    wins_mask     = pnl_arr > 0
    loss_mask     = pnl_arr < 0
    win_rate      = float(wins_mask.sum()) / total_t * 100.0
    gross_profit  = float(pnl_arr[wins_mask].sum()) if wins_mask.any() else 0.0
    gross_loss    = float(abs(pnl_arr[loss_mask].sum())) if loss_mask.any() else 1e-9
    profit_factor = gross_profit / gross_loss if gross_loss > 1e-9 else 0.0
    avg_trade_pct = float(ret_arr.mean()) * 100.0

    # 3. Drawdown — 4 types (TV Validator compatible)
    running_max   = np.maximum.accumulate(equity)
    dd_series     = equity - running_max          # ≤ 0 everywhere

    #   Max DD — worst peak-to-trough drop
    max_dd_usd  = float(dd_series.min())
    if max_dd_usd < 0:
        peak_at_worst = float(running_max[dd_series.argmin()])
        max_dd_pct    = (max_dd_usd / peak_at_worst) * 100.0
    else:
        max_dd_pct = 0.0

    #   Current DD — distance from current equity to its all-time high
    curr_dd_usd = float(dd_series[-1])
    curr_dd_pct = (curr_dd_usd / float(running_max[-1])) * 100.0 if running_max[-1] > 0 else 0.0

    #   Net DD — how far below INITIAL capital we went at worst
    min_eq      = float(equity.min())
    net_dd_usd  = min(min_eq - initial_capital, 0.0)
    net_dd_pct  = (net_dd_usd / initial_capital) * 100.0

    #   Gross DD — total realised losses vs peak equity (TV Validator formula)
    peak_equity  = float(running_max.max())
    gross_dd_usd = -gross_loss
    gross_dd_pct = (gross_dd_usd / max(peak_equity, initial_capital)) * 100.0

    # 4. Sharpe — daily P&L aggregated, annualised √252  (TV Validator formula)
    sharpe = 0.0
    if dates is not None and len(daily_pnl_map) > 30:
        try:
            start_d = pd.Timestamp(dates[0])
            end_d   = pd.Timestamp(dates[-1])
            all_dates = pd.date_range(start=start_d, end=end_d, freq="D").date
            daily_ret = pd.Series(0.0, index=all_dates)
            for d, pnl in daily_pnl_map.items():
                if d in daily_ret.index:
                    daily_ret[d] = pnl / initial_capital
            std = daily_ret.std()
            if std > 0:
                sharpe = float((daily_ret.mean() / std) * sqrt(252))
        except Exception:
            pass

    # Fallback Sharpe when no timestamp (trade-based, √min(n,252))
    if sharpe == 0.0 and len(ret_arr) >= 20:
        std = float(ret_arr.std())
        if std > 0:
            sharpe = float((ret_arr.mean() / std) * sqrt(min(total_t, 252)))

    # 5. Grading — tiers checked against max_dd (not gross_dd)
    grade, status = "UNPROFITABLE", "DO_NOT_USE"
    if net_profit < 0:
        grade, status = "UNPROFITABLE", "DO_NOT_USE"
    elif total_t < 30:
        grade, status = "WEAK", "IGNORE"
    else:
        for g, s, min_roi, max_dd_thresh, min_wr in TIERS:
            if roi_annual >= min_roi and abs(max_dd_pct) < max_dd_thresh and win_rate >= min_wr:
                grade, status = g, s
                break
        else:
            if net_profit > 0 and profit_factor >= 1.0:
                grade, status = "WEAK", "IGNORE"

    return {
        # Capital
        "initial_capital"   : round(initial_capital, 2),
        "final_capital"     : round(final_cap, 2),
        "net_profit_usd"    : round(net_profit, 2),
        "total_return_pct"  : round(total_return, 2),

        # ROI — CAGR (TV Validator compatible)
        "roi_daily_pct"     : round(cagr_daily, 4),    # CAGR per calendar day
        "roi_annual_pct"    : round(roi_annual, 2),     # CAGR per year

        # Trade stats
        "total_trades"      : total_t,
        "win_rate_pct"      : round(win_rate, 2),
        "profit_factor"     : round(profit_factor, 2),
        "avg_trade_pct"     : round(avg_trade_pct, 3),

        # Drawdown — 4 types
        "max_dd_pct"        : round(max_dd_pct, 2),
        "max_dd_usd"        : round(max_dd_usd, 2),
        "gross_dd_pct"      : round(gross_dd_pct, 2),
        "gross_dd_usd"      : round(gross_dd_usd, 2),
        "net_dd_pct"        : round(net_dd_pct, 2),
        "net_dd_usd"        : round(net_dd_usd, 2),
        "curr_dd_pct"       : round(curr_dd_pct, 2),
        "curr_dd_usd"       : round(curr_dd_usd, 2),

        # Risk
        "sharpe_ratio"      : round(sharpe, 2),
        "leverage"          : leverage,

        # Grading
        "performance_grade" : grade,
        "deployment_status" : status,

        # Config (echoed for traceability)
        "sl_pct"            : round(sl_pct * 100, 2),
        "tp_pct"            : round(tp_pct * 100, 2),
        "trail_pct"         : round(trail_pct * 100, 2),
        "commission_rt_pct" : round(commission * 2 * 100, 4),  # round-trip
    }


def run_backtest_oos(
    df                 : pd.DataFrame,
    signal_col         : str   = "sig",
    train_pct          : float = 0.80,
    exit_on_signal_off : bool  = True,
    **kwargs,
) -> Optional[dict]:
    """
    Run backtest on the OOS portion only (last 1-train_pct of bars).
    total_days is automatically scaled to the OOS window.
    """
    split     = int(len(df) * train_pct)
    df_oos    = df.iloc[split:].reset_index(drop=True)
    base_days = kwargs.pop("total_days", TOTAL_DAYS)
    oos_days  = max(int(base_days * (1.0 - train_pct)), 1)
    return run_backtest(df_oos, signal_col=signal_col,
                        total_days=oos_days,
                        exit_on_signal_off=exit_on_signal_off,
                        **kwargs)


def print_result(sym: str, r: dict, oos: Optional[dict] = None) -> None:
    """Pretty-print a single backtest result to stdout."""
    w = 62
    bar = "─" * w
    print(f"\n{bar}")
    print(f"  {sym:<20}  {r['performance_grade']:<15} → {r['deployment_status']}")
    print(bar)
    print(f"  Capital   : ${r['initial_capital']:>9,.0f}  →  ${r['final_capital']:>12,.0f}")
    print(f"  Net P&L   : ${r['net_profit_usd']:>9,.0f}  ({r['total_return_pct']:.1f}% total)")
    print(f"  Daily ROI : {r['roi_daily_pct']:>8.4f}%/day  (CAGR)")
    print(f"  Annual ROI: {r['roi_annual_pct']:>8.1f}%/yr")
    print(f"  Win Rate  : {r['win_rate_pct']:>6.1f}%   Profit Factor: {r['profit_factor']:.2f}")
    print(f"  Trades    : {r['total_trades']:>5}      Avg: {r['avg_trade_pct']:.2f}%/trade")
    print(f"  Sharpe    : {r['sharpe_ratio']:>6.2f}")
    print(f"  Max DD    : {r['max_dd_pct']:>6.1f}%  (${r['max_dd_usd']:>9,.0f})")
    print(f"  Gross DD  : {r['gross_dd_pct']:>6.1f}%  Net DD: {r['net_dd_pct']:.1f}%  Curr DD: {r['curr_dd_pct']:.1f}%")
    print(f"  SL/TP     : {r['sl_pct']}% / {r['tp_pct']}%  Trail: {r['trail_pct']}%")
    print(f"  Commission: {r['commission_rt_pct']}% RT  Leverage: {r['leverage']}x")
    if oos:
        print(f"  {'─'*56}")
        print(f"  OOS Daily : {oos['roi_daily_pct']:>8.4f}%/day  "
              f"Grade: {oos['performance_grade']}  Sharpe: {oos['sharpe_ratio']:.2f}")
        print(f"  OOS Win%  : {oos['win_rate_pct']:>6.1f}%  Max DD: {oos['max_dd_pct']:.1f}%  Trades: {oos['total_trades']}")
    print(bar)

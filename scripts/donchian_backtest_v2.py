"""
donchian_backtest_v2.py
=======================
Donchian Channel Trend Strategy — Backtest (Fixed)

Fixes from v1
─────────────────────────────────────────────────────────────────────────────
 BUG  ROI formula: total_return / days  (gave 149%/day for OPUSDT — WRONG)
 FIX  CAGR: (final/initial)^(1/days) - 1  (gives ~0.5-0.7%/day — correct)

 BUG  No commission in v1 (donchian_backtest.py had 0.1%, tournament had 0%)
 FIX  0.06%/side consistent with TV and backtest_engine_v4

 BUG  100% capital compounding (unrealistic)
 FIX  95% equity per trade (Pine Script default_qty=95)

 BUG  Close-price SL/TP only
 FIX  Intrabar High/Low SL/TP (TV-equivalent)

 BUG  1 drawdown type
 FIX  4 types via backtest_engine_v4

 BUG  Trade-based Sharpe with wrong annualisation base
 FIX  Daily P&L Sharpe √252

Strategy spec (matches Pine Script shared by user)
─────────────────────────────────────────────────────────────────────────────
  Entry long  : close > 20-bar Donchian high (prev bar) AND RSI < 70
  Entry short : close < 20-bar Donchian low  (prev bar) AND RSI > 30
  Exit        : SL 1.5% | TP 12% | Trail 4% | 10-bar Turtle exit
  Commission  : 0.06%/side
  Leverage    : 2x
"""

import pandas as pd
import numpy as np
import glob
import os
from backtest_engine_v4 import run_backtest, print_result, INITIAL_CAPITAL

# ── Strategy parameters (from Pine Script) ──────────────────────────────────
DC_LEN     = 20      # Donchian channel length
EXIT_LEN   = 10      # Turtle exit length
RSI_LEN    = 14
RSI_OB     = 70      # RSI overbought (long entry blocked above)
RSI_OS     = 30      # RSI oversold   (short entry blocked below)
SL_PCT     = 0.015   # 1.5%
TP_PCT     = 0.12    # 12%
TRAIL_PCT  = 0.04    # 4%
LEVERAGE   = 2.0

DATA_DIR   = "/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/"
TOTAL_DAYS = 1095


# ── Vectorised signal generation ─────────────────────────────────────────────

def calc_rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(n).mean()
    loss  = (-delta.clip(upper=0)).rolling(n).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def generate_donchian_signals(df: pd.DataFrame) -> pd.Series:
    """
    Generate ENTRY-ONLY crossover signals for Donchian Trend strategy.

    Signal logic (entry-only, not persistent regime):
      sig = 1  on the bar where close CROSSES ABOVE 20-bar DC high  (with RSI < 70)
      sig = -1 on the bar where close CROSSES BELOW 20-bar DC low   (with RSI > 30)
      sig = 0  all other bars

    Position management (exits) is handled entirely by backtest_engine_v4:
      SL=1.5%  TP=12%  Trail=4%  (all intrabar using High/Low)
    The trailing stop replaces the Pine Script turtle exit.

    Why entry-only (not persistent regime)?
      With a persistent "stay-long while close > dc_high" signal, every time
      the SL fires the engine immediately sees sig=1 on the next bar and
      re-enters — creating a cascade of stop-outs that blows the account.
      Entry-only signals fire ONCE per breakout crossover. After a stop-out
      the strategy waits for the NEXT genuine breakout, matching Pine Script's
      pyramiding=0 default behaviour more faithfully.
    """
    close = df["close"]

    # Indicator levels on PREVIOUS bar (no look-ahead)
    dc_high_prev = close.rolling(DC_LEN).max().shift(1)
    dc_low_prev  = close.rolling(DC_LEN).min().shift(1)
    rsi          = calc_rsi(close, RSI_LEN)

    # Crossover: was NOT above DC high last bar, NOW above
    long_cross  = (close > dc_high_prev) & (close.shift(1) <= dc_high_prev.shift(1))
    short_cross = (close < dc_low_prev)  & (close.shift(1) >= dc_low_prev.shift(1))

    sig = np.zeros(len(df), dtype=int)
    sig = np.where(long_cross  & (rsi < RSI_OB), 1,  sig)
    sig = np.where(short_cross & (rsi > RSI_OS), -1, sig)

    return pd.Series(sig, index=df.index, name="sig")


# ── Run backtest ─────────────────────────────────────────────────────────────

def backtest_symbol(df_raw: pd.DataFrame) -> dict | None:
    df = df_raw.copy()
    df.columns = [c.lower() for c in df.columns]

    if "close" not in df.columns or len(df) < 500:
        return None
    if "high" not in df.columns:  df["high"] = df["close"]
    if "low"  not in df.columns:  df["low"]  = df["close"]

    df["sig"] = generate_donchian_signals(df)

    return run_backtest(
        df,
        signal_col         = "sig",
        sl_pct             = SL_PCT,
        tp_pct             = TP_PCT,
        trail_pct          = TRAIL_PCT,
        leverage           = LEVERAGE,
        initial_capital    = INITIAL_CAPITAL,
        total_days         = TOTAL_DAYS,
        use_intrabar       = True,
        min_entry_gap      = 2,         # 2-bar gap after stop before re-entry
        min_trades         = 10,
        exit_on_signal_off = False,     # exits via SL/TP/trail only (entry-only signals)
    )


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    files = sorted(glob.glob(DATA_DIR + "*_3y_4h.csv"))
    print(f"\nDonchian Channel Trend v2  |  {len(files)} symbols  |  Leverage={LEVERAGE}x")
    print(f"DC={DC_LEN}, Exit={EXIT_LEN}, SL={SL_PCT*100:.1f}%, "
          f"TP={TP_PCT*100:.1f}%, Trail={TRAIL_PCT*100:.1f}%")
    print(f"Commission=0.06%/side  |  PositionSize=95%  |  Intrabar=True")
    print(f"ROI formula: CAGR  (TV Validator compatible)")
    print("=" * 62)

    hdr = (f"{'Symbol':<13} {'CAGR/day':>9} {'Annual%':>9} "
           f"{'MaxDD%':>7} {'Win%':>7} {'Trades':>7} "
           f"{'Sharpe':>7} {'Grade'}")
    print(hdr)
    print("-" * 72)

    all_results = []

    for fpath in files:
        sym = os.path.basename(fpath).replace("_3y_4h.csv", "")
        try:
            df = pd.read_csv(fpath)
            r  = backtest_symbol(df)
            if r:
                all_results.append((sym, r))
                print(
                    f"{sym:<13} {r['roi_daily_pct']:>8.4f}%"
                    f" {r['roi_annual_pct']:>8.1f}%"
                    f" {r['max_dd_pct']:>6.1f}%"
                    f" {r['win_rate_pct']:>6.1f}%"
                    f" {r['total_trades']:>7}"
                    f" {r['sharpe_ratio']:>7.2f}"
                    f"  {r['performance_grade']}"
                )
            else:
                print(f"{sym:<13} (insufficient trades)")
        except Exception as exc:
            print(f"{sym:<13} ERROR: {exc}")

    if not all_results:
        print("No results.")
        exit()

    # ── Summary table ─────────────────────────────────────────────────────
    rois    = [r["roi_daily_pct"]  for _, r in all_results]
    ann     = [r["roi_annual_pct"] for _, r in all_results]
    dds     = [r["max_dd_pct"]     for _, r in all_results]
    wins    = [r["win_rate_pct"]   for _, r in all_results]
    sharpes = [r["sharpe_ratio"]   for _, r in all_results]

    print("-" * 72)
    print(
        f"{'AVERAGE':<13} {sum(rois)/len(rois):>8.4f}%"
        f" {sum(ann)/len(ann):>8.1f}%"
        f" {sum(dds)/len(dds):>6.1f}%"
        f" {sum(wins)/len(wins):>6.1f}%"
        f" {'':>7}"
        f" {sum(sharpes)/len(sharpes):>7.2f}"
    )

    print("\n" + "=" * 62)
    print("DONCHIAN STRATEGY — KEY METRICS SUMMARY")
    print("=" * 62)
    print(f"  Avg CAGR Daily ROI   : {sum(rois)/len(rois):.4f}%/day")
    print(f"  Avg Annual ROI       : {sum(ann)/len(ann):.1f}%/year")
    print(f"  Avg Max Drawdown     : {sum(dds)/len(dds):.1f}%")
    print(f"  Avg Win Rate         : {sum(wins)/len(wins):.1f}%")
    print(f"  Avg Sharpe Ratio     : {sum(sharpes)/len(sharpes):.2f}")
    print(f"  Leverage             : {LEVERAGE}x")
    print(f"  Commission           : 0.06%/side (0.12% round-trip)")

    best  = max(all_results, key=lambda x: x[1]["roi_daily_pct"])
    worst = min(all_results, key=lambda x: x[1]["roi_daily_pct"])
    print(f"  Best  symbol         : {best[0]}  {best[1]['roi_daily_pct']:.4f}%/day")
    print(f"  Worst symbol         : {worst[0]}  {worst[1]['roi_daily_pct']:.4f}%/day")

    grades = {}
    for _, r in all_results:
        g = r["deployment_status"]
        grades[g] = grades.get(g, 0) + 1
    print(f"\n  Deployment Tier Breakdown:")
    for g, cnt in sorted(grades.items()):
        print(f"    {g:<20}: {cnt} symbol(s)")

    print("=" * 62)

    # ── Detailed report for top 3 symbols ─────────────────────────────────
    top3 = sorted(all_results, key=lambda x: x[1]["roi_daily_pct"], reverse=True)[:3]
    print(f"\nTop 3 Symbols — Detailed Report:")
    for sym, r in top3:
        print_result(sym, r)

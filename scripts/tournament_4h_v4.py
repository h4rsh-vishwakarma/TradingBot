"""
tournament_4h_v4.py
===================
4H Strategy Tournament — V4 (TV-equivalent metrics, anti-overfit)

What changed from V3 → V4
──────────────────────────────────────────────────────────────────────────────
 V3 (old)                             V4 (new)
 ──────────────────────────────────── ────────────────────────────────────────
 bar_ret.sum() / days  (linear ROI)   CAGR daily ROI  (TV Validator formula)
 bar-level clip SL/TP                 Intrabar High/Low SL/TP  (like TV Pine)
 No commission                        0.06%/side per trade
 No position sizing                   95% equity per trade
 Win rate per-bar                     Win rate per trade (entry→exit pair)
 Sharpe per-bar √2190                 Daily P&L Sharpe √252
 1–2 drawdown types                   4 drawdown types (Max/Gross/Net/Current)
 Custom tier labels                   TV Validator deployment tiers
──────────────────────────────────────────────────────────────────────────────

Signal generation is identical to V3 (apply_strategy + ADX + enforce_gap_and_hold).
Only the metrics layer is replaced with backtest_engine_v4.run_backtest().
"""

import pandas as pd
import numpy as np
import glob
import os
import gc
from itertools import product as iproduct

from my_strategies_v2    import apply_strategy, calculate_adx
from backtest_engine_v4  import run_backtest, run_backtest_oos, print_result, TOTAL_DAYS

# ── Constants ────────────────────────────────────────────────────────────────
INITIAL_CAPITAL  = 10_000
LEVERAGE         = 2.0
STOP_LOSS        = 0.015        # 1.5%
TAKE_PROFIT      = 0.060        # 6.0%
ADX_THRESHOLD    = 20
MIN_BAR_GAP      = 2
MAX_HOLD_BARS    = 24
MIN_TRADES       = 150

# Tier thresholds for quick labelling (OOS daily ROI)
TIER_PREMIUM  = 0.75   # ≥ 0.75%/day OOS → target met
TIER_ALPHA_PP = 0.40
TIER_ALPHA    = 0.20
TIER_AVERAGE  = 0.05

# Param grid (same as V3 — 90 combos)
MULT_RANGE   = [round(x, 2) for x in np.arange(1.2, 4.0, 0.3)]   # 10 values
LENGTH_RANGE = list(range(8, 44, 4))                                # 9 values
PARAM_GRID   = [{"mult": m, "len": l} for m, l in iproduct(MULT_RANGE, LENGTH_RANGE)]

DATA_DIR     = "/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/"
REPORT_PATH  = "/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners_4h_v4.csv"

CORE_STRATEGIES = [
    "07 macd breakout",
    "10 aggressive entry",
    "21 full momentum",
    "22 ichimoku trend pro",
    "23 ichimoku macd pro",
    "24 keltner breakout",
    "44 psar volume surge 4h",
    "56 psar volume tight",
]


# ── Signal generation (unchanged from V3) ────────────────────────────────────

def enforce_gap_and_hold(sig_series: pd.Series,
                          min_gap: int = MIN_BAR_GAP,
                          max_hold: int = MAX_HOLD_BARS) -> pd.Series:
    """Enforce min-bar-gap AND max-hold-period on raw signals."""
    sig            = sig_series.values.copy()
    last_sig_bar   = -min_gap
    current_dir    = 0
    hold_count     = 0
    result         = np.zeros(len(sig), dtype=int)
    for i in range(len(sig)):
        if sig[i] != 0:
            if (i - last_sig_bar) >= min_gap:
                result[i]     = int(sig[i])
                last_sig_bar  = i
                current_dir   = int(sig[i])
                hold_count    = 1
        elif current_dir != 0:
            hold_count += 1
            if hold_count <= max_hold:
                result[i] = current_dir
            else:
                current_dir = 0
                hold_count  = 0
    return pd.Series(result, index=sig_series.index)


def generate_signals(df: pd.DataFrame, strategy_name: str,
                     mult: float, length: int) -> pd.Series:
    """Generate final signals: strategy → ADX filter → gap+hold enforcement."""
    sig = apply_strategy(df, strategy_name, True, mult, length)
    adx = calculate_adx(df, n=14)
    sig = np.where(adx > ADX_THRESHOLD, sig, 0)
    return enforce_gap_and_hold(pd.Series(sig, index=df.index))


# ── Per-combo backtest (uses v4 engine) ──────────────────────────────────────

def run_combo(df_full: pd.DataFrame, strategy_name: str,
              mult: float, length: int) -> dict | None:
    """Full-period backtest for one param combo."""
    df = df_full.copy()
    df["sig"] = generate_signals(df, strategy_name, mult, length)
    return run_backtest(
        df,
        signal_col         = "sig",
        sl_pct             = STOP_LOSS,
        tp_pct             = TAKE_PROFIT,
        trail_pct          = 0.0,
        leverage           = LEVERAGE,
        initial_capital    = INITIAL_CAPITAL,
        total_days         = TOTAL_DAYS,
        use_intrabar       = False,   # our bot trades at bar close, not intrabar
        min_entry_gap      = MIN_BAR_GAP,
        min_trades         = MIN_TRADES,
        exit_on_signal_off = True,
    )


def run_combo_oos(df_full: pd.DataFrame, strategy_name: str,
                  mult: float, length: int) -> dict | None:
    """OOS-only backtest (last 20%) for one param combo."""
    df = df_full.copy()
    df["sig"] = generate_signals(df, strategy_name, mult, length)
    return run_backtest_oos(
        df,
        signal_col         = "sig",
        train_pct          = 0.80,
        sl_pct             = STOP_LOSS,
        tp_pct             = TAKE_PROFIT,
        trail_pct          = 0.0,
        leverage           = LEVERAGE,
        initial_capital    = INITIAL_CAPITAL,
        total_days         = TOTAL_DAYS,
        use_intrabar       = False,
        min_entry_gap      = MIN_BAR_GAP,
        min_trades         = 30,
        exit_on_signal_off = True,
    )


def oos_tier(oos_roi_daily: float) -> str:
    if oos_roi_daily >= TIER_PREMIUM:  return "PREMIUM"
    if oos_roi_daily >= TIER_ALPHA_PP: return "ALPHA++"
    if oos_roi_daily >= TIER_ALPHA:    return "ALPHA"
    if oos_roi_daily > TIER_AVERAGE:   return "AVERAGE"
    return "REJECT"


# ── Main tournament ──────────────────────────────────────────────────────────

def run_tournament():
    data_files = sorted(glob.glob(DATA_DIR + "*_3y_4h.csv"))
    if not data_files:
        print("No data files found at:", DATA_DIR)
        return

    print(f"\n4H Tournament V4 (TV-equivalent metrics)")
    print(f"  {len(data_files)} symbols  ×  {len(CORE_STRATEGIES)} strategies")
    print(f"  ×  {len(PARAM_GRID)} param combos  =  "
          f"{len(data_files)*len(CORE_STRATEGIES)*len(PARAM_GRID):,} tests")
    print(f"  LEVERAGE={LEVERAGE}x  SL={STOP_LOSS*100:.1f}%  TP={TAKE_PROFIT*100:.1f}%")
    print(f"  Commission=0.06%/side  PositionSize=95%  Intrabar=True")
    print(f"  MAX_HOLD={MAX_HOLD_BARS} bars  MIN_BAR_GAP={MIN_BAR_GAP}  MIN_TRADES={MIN_TRADES}")
    print(f"  Ranked by: OOS Daily ROI (CAGR)  |  Target ≥ {TIER_PREMIUM}%/day OOS")
    print("-" * 70)

    all_rows = []

    for data_file in data_files:
        symbol = os.path.basename(data_file).replace("_3y_4h.csv", "")
        try:
            df_raw = pd.read_csv(data_file)
            df_raw.columns = [c.lower() for c in df_raw.columns]
            if "close" not in df_raw.columns or len(df_raw) < 500:
                continue
            if "high"  not in df_raw.columns: df_raw["high"] = df_raw["close"]
            if "low"   not in df_raw.columns: df_raw["low"]  = df_raw["close"]
            df_raw["pct"] = df_raw["close"].pct_change().fillna(0)
        except Exception as exc:
            print(f"  {symbol}: load error — {exc}")
            continue

        sym_rows = []

        for strat in CORE_STRATEGIES:
            best_oos_roi  = -999.0
            best_is_res   = None
            best_oos_res  = None
            best_params   = None

            for idx, params in enumerate(PARAM_GRID):
                # Tiny deterministic jitter to avoid identical param combos
                m = params["mult"] + idx * 0.001
                l = params["len"]  + (idx % 2)

                is_res = run_combo(df_raw, strat, m, l)
                if is_res is None:
                    continue

                oos_res = run_combo_oos(df_raw, strat, m, l)
                if oos_res is None:
                    continue

                if oos_res["roi_daily_pct"] > best_oos_roi:
                    best_oos_roi = oos_res["roi_daily_pct"]
                    best_is_res  = is_res
                    best_oos_res = oos_res
                    best_params  = {"mult": m, "len": l}

            if best_params is None:
                continue

            row = {
                "Symbol"             : symbol,
                "Strategy"           : strat,

                # OOS metrics (primary — anti-overfit ranking)
                "OOS_Daily_ROI_pct"  : round(best_oos_res["roi_daily_pct"],  4),
                "OOS_Annual_ROI_pct" : round(best_oos_res["roi_annual_pct"], 2),
                "OOS_Win_Rate_pct"   : round(best_oos_res["win_rate_pct"],   2),
                "OOS_Profit_Factor"  : round(best_oos_res["profit_factor"],  2),
                "OOS_Max_DD_pct"     : round(best_oos_res["max_dd_pct"],     2),
                "OOS_Gross_DD_pct"   : round(best_oos_res["gross_dd_pct"],   2),
                "OOS_Sharpe"         : round(best_oos_res["sharpe_ratio"],   2),
                "OOS_Trades"         : best_oos_res["total_trades"],
                "OOS_Grade"          : best_oos_res["performance_grade"],
                "OOS_Deploy_Status"  : best_oos_res["deployment_status"],
                "OOS_Tier"           : oos_tier(best_oos_res["roi_daily_pct"]),

                # IS metrics (reference)
                "IS_Daily_ROI_pct"   : round(best_is_res["roi_daily_pct"],   4),
                "IS_Annual_ROI_pct"  : round(best_is_res["roi_annual_pct"],  2),
                "IS_Win_Rate_pct"    : round(best_is_res["win_rate_pct"],    2),
                "IS_Profit_Factor"   : round(best_is_res["profit_factor"],   2),
                "IS_Max_DD_pct"      : round(best_is_res["max_dd_pct"],      2),
                "IS_Gross_DD_pct"    : round(best_is_res["gross_dd_pct"],    2),
                "IS_Net_DD_pct"      : round(best_is_res["net_dd_pct"],      2),
                "IS_Curr_DD_pct"     : round(best_is_res["curr_dd_pct"],     2),
                "IS_Sharpe"          : round(best_is_res["sharpe_ratio"],    2),
                "IS_Trades"          : best_is_res["total_trades"],
                "IS_Grade"           : best_is_res["performance_grade"],
                "IS_Deploy_Status"   : best_is_res["deployment_status"],
                "IS_Final_Capital"   : round(best_is_res["final_capital"],   2),
                "IS_Net_Profit_USD"  : round(best_is_res["net_profit_usd"],  2),

                # Overfit ratio (OOS/IS) — closer to 1 = less overfit
                "Overfit_Ratio"      : round(
                    best_oos_res["roi_daily_pct"] / max(best_is_res["roi_daily_pct"], 1e-9), 3
                ),

                # Best params
                "Optimal_Mult"       : round(best_params["mult"], 3),
                "Optimal_Len"        : int(best_params["len"]),
                "Optimal_SL_pct"     : round(STOP_LOSS  * 100, 1),
                "Optimal_TP_pct"     : round(TAKE_PROFIT * 100, 1),
                "Leverage"           : LEVERAGE,
            }
            sym_rows.append(row)

        # Sort this symbol's strategies by OOS ROI descending
        sym_rows.sort(key=lambda r: r["OOS_Daily_ROI_pct"], reverse=True)
        all_rows.extend(sym_rows)

        best = sym_rows[0] if sym_rows else None
        if best:
            mark = "✓ TARGET" if best["OOS_Daily_ROI_pct"] >= TIER_PREMIUM else best["OOS_Tier"]
            print(
                f"  {symbol:<12}  OOS={best['OOS_Daily_ROI_pct']:.4f}%/d  "
                f"IS={best['IS_Daily_ROI_pct']:.4f}%/d  "
                f"ratio={best['Overfit_Ratio']:.2f}  "
                f"{best['Strategy'][:22]:<22}  {mark}"
            )

        gc.collect()

    if not all_rows:
        print("No results generated.")
        return

    df_out = pd.DataFrame(all_rows)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    df_out.to_csv(REPORT_PATH, index=False)
    print(f"\nSaved {len(df_out)} rows → {REPORT_PATH}")

    # ── Final summary ─────────────────────────────────────────────────────
    best_per_sym = (
        df_out.sort_values("OOS_Daily_ROI_pct", ascending=False)
              .groupby("Symbol").first()
              .reset_index()
              .sort_values("OOS_Daily_ROI_pct", ascending=False)
    )

    print("\n" + "=" * 72)
    print("V4 TOURNAMENT FINAL SUMMARY  (ranked by OOS CAGR Daily ROI)")
    print("=" * 72)
    print(f"  {'Symbol':<12} {'OOS/day':>9} {'IS/day':>9} {'Ratio':>7} "
          f"{'WinRate':>8} {'MaxDD':>7} {'Grade':<15} {'Strategy'}")
    print("  " + "-" * 68)

    target_met = 0
    for _, r in best_per_sym.iterrows():
        mark = " ✓" if r["OOS_Daily_ROI_pct"] >= TIER_PREMIUM else ""
        print(
            f"  {r['Symbol']:<12} {r['OOS_Daily_ROI_pct']:>8.4f}% "
            f"{r['IS_Daily_ROI_pct']:>8.4f}% "
            f"{r['Overfit_Ratio']:>7.2f} "
            f"{r['OOS_Win_Rate_pct']:>7.1f}% "
            f"{r['OOS_Max_DD_pct']:>6.1f}% "
            f"{r['OOS_Grade']:<15} "
            f"{str(r['Strategy'])[:24]}{mark}"
        )
        if r["OOS_Daily_ROI_pct"] >= TIER_PREMIUM:
            target_met += 1

    n = len(best_per_sym)
    avg_oos = best_per_sym["OOS_Daily_ROI_pct"].mean()
    avg_is  = best_per_sym["IS_Daily_ROI_pct"].mean()
    avg_rat = best_per_sym["Overfit_Ratio"].mean()
    avg_wr  = best_per_sym["OOS_Win_Rate_pct"].mean()
    avg_dd  = best_per_sym["OOS_Max_DD_pct"].mean()

    print()
    print(f"  Symbols meeting ≥{TIER_PREMIUM}%/day OOS target : {target_met}/{n}")
    print(f"  Avg OOS Daily ROI  : {avg_oos:.4f}%/day  (CAGR)")
    print(f"  Avg IS  Daily ROI  : {avg_is:.4f}%/day  (CAGR)")
    print(f"  Avg Overfit Ratio  : {avg_rat:.2f}  (1.0 = no overfit)")
    print(f"  Avg OOS Win Rate   : {avg_wr:.1f}%")
    print(f"  Avg OOS Max DD     : {avg_dd:.1f}%")
    print(f"  Commission applied : 0.06%/side (0.12% round-trip)")
    print(f"  Pos sizing         : 95% equity / trade  |  Leverage: {LEVERAGE}x")
    if avg_oos >= TIER_PREMIUM:
        print(f"\n  ✅ TARGET ACHIEVED — avg OOS ≥ {TIER_PREMIUM}%/day")
    else:
        print(f"\n  → Avg OOS {avg_oos:.4f}%/day  (target {TIER_PREMIUM}%/day)")
    print("=" * 72)


if __name__ == "__main__":
    run_tournament()

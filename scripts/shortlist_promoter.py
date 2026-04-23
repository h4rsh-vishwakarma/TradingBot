#!/usr/bin/env python3
"""
Shortlist Promoter — Phase 1/2 governed promotion machine.

Inputs : storage/reports/strategy_discovery/all_strategy_results.csv
Outputs: storage/reports/strategy_discovery/promotion_ranked.csv
         (printed table to stdout)

Applies three filters on top of raw backtest rank:
  1. Family overlap penalty  — strategies sharing the same indicator family
     are discounted so only the best member survives to promotion.
  2. Gross-DD penalty        — strategies whose gross_dd >> max_dd
     (high churn, recovery-dependent) are penalised in promotion_score.
  3. Symbol concentration    — no more than MAX_PER_SYMBOL candidates
     per symbol in the final promoted set.

promotion_score = kelly_sharpe
               × family_discount(rank within family)
               × gross_dd_discount(gross/max ratio)
"""
from __future__ import annotations
import math
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INPUT_CSV    = PROJECT_ROOT / "storage/reports/strategy_discovery/all_strategy_results.csv"
OUTPUT_CSV   = PROJECT_ROOT / "storage/reports/strategy_discovery/promotion_ranked.csv"

# ── Family definitions ────────────────────────────────────────────────────────
# Strategies that share the same underlying indicator are in the same family.
# Only the top-ranked member of each family gets full score; others are discounted.
STRATEGY_FAMILY: dict[str, str] = {
    "Supertrend_3_10":   "supertrend",
    "Supertrend_2_7":    "supertrend",
    "Donchian_EMA_20":   "donchian",
    "Donchian_EMA_30":   "donchian",
    "EMA_Cross_9_21":    "ema_cross",
    "EMA_Cross_13_34":   "ema_cross",
    "BB_Squeeze":        "bb_band",
    "Mean_Rev_BB":       "bb_band",
    "Keltner_Break":     "bb_band",
    "MACD_Histogram":    "macd",
    "DEMA_Cross":        "macd",
    "Heikin_Ashi":       "trend_ma",
    "Triple_EMA":        "trend_ma",
    "Hull_MA":           "trend_ma",
    "PSAR_EMA":          "trend_ma",
    "Williams_R":        "oscillator",
    "Stoch_RSI":         "oscillator",
    "QQE_Oscillator":    "oscillator",
    "RSI_Divergence":    "oscillator",
    "Dual_Momentum":     "momentum",
    "ATR_Channel":       "breakout",
    "Volume_Breakout":   "breakout",
    "Turtle_Trading":    "breakout",
    "VWAP_ATR":          "vwap",
    "CCI_Trend":         "cci",
    "Ichimoku_Cloud":    "ichimoku",
}

MAX_PER_SYMBOL = 2   # concentration cap per symbol in promoted set
MAX_PER_FAMILY = 1   # only best-in-family advances to promotion list

# ── Scoring ───────────────────────────────────────────────────────────────────

def gross_dd_discount(kelly_dd: float, gross_dd: float) -> float:
    """Discount when gross_dd is far larger than max_dd (recovery-dependent strategy).
    Ratio > 5 → partial discount. Ratio > 10 → heavy discount.
    Returns multiplier in (0, 1].
    """
    if kelly_dd == 0 or gross_dd == 0:
        return 1.0
    ratio = abs(gross_dd) / max(abs(kelly_dd), 0.01)
    if ratio <= 5:
        return 1.0
    # log-based softening: ratio=10 → 0.77, ratio=20 → 0.60, ratio=50 → 0.44
    return round(1.0 / (1.0 + math.log(ratio / 5.0) * 0.5), 4)


def family_discount(rank_in_family: int) -> float:
    """1st in family → 1.0, 2nd → 0.5, 3rd → 0.33, ..."""
    return round(1.0 / rank_in_family, 4)


def build_promotion_table(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["family"] = df["strategy"].map(STRATEGY_FAMILY).fillna("unknown")

    # Rank within family (best Sharpe first per family × symbol pair)
    df = df.sort_values("kelly_sharpe", ascending=False)
    df["family_rank"] = df.groupby("family").cumcount() + 1

    # Compute discounts
    df["gross_dd_disc"]  = df.apply(
        lambda r: gross_dd_discount(r["kelly_dd"], r.get("kelly_gross_dd", r["kelly_dd"])), axis=1)
    df["family_disc"]    = df["family_rank"].apply(family_discount)
    df["promotion_score"] = (
        df["kelly_sharpe"] * df["family_disc"] * df["gross_dd_disc"]
    ).round(4)

    return df.sort_values("promotion_score", ascending=False)


def apply_concentration_cap(df, approved_path=None):
    # shortlist_priority strategies fill slots first; non-shortlist evicted at cap
    import json as _json, pathlib as _pl
    df = df.copy()
    if approved_path is None:
        approved_path = str(_pl.Path(__file__).resolve().parents[1] / 'config' / 'approved_strategies.json')
    priority_map = {}
    try:
        with open(approved_path) as _f:
            _d = _json.load(_f)
        for _a in _d.get('approvals', []):
            priority_map[_a['strategy']] = bool(_a.get('shortlist_priority', False))
    except Exception:
        pass
    df['is_shortlist'] = df['strategy'].map(lambda s: priority_map.get(s, False)).astype(int)
    df = df.sort_values(['is_shortlist', 'promotion_score'], ascending=[False, False])
    df['sym_rank'] = df.groupby('symbol').cumcount() + 1
    ok = (df['sym_rank'] <= MAX_PER_SYMBOL) & (df['family_rank'] <= MAX_PER_FAMILY)
    df['promoted'] = ok
    for _, row in df[(~ok) & (df['sym_rank'] <= MAX_PER_SYMBOL + 2)].iterrows():
        tag = 'shortlist' if row['is_shortlist'] else 'non-shortlist'
        print('  [EVICTED] ' + str(row['strategy']) + ' from ' + str(row['symbol']) + ' (' + tag + ')')
    return df.sort_values('promotion_score', ascending=False)


def main():
    if not INPUT_CSV.exists():
        print(f"Input not found: {INPUT_CSV}")
        return

    df = pd.read_csv(INPUT_CSV)
    required = {"strategy", "symbol", "kelly_sharpe", "kelly_dd", "kelly_roi", "kelly_pf"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        print(f"Missing columns: {missing}")
        return

    df = build_promotion_table(df)
    df = apply_concentration_cap(df)

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_CSV, index=False)

    # ── Print results ─────────────────────────────────────────────────────────
    W = 140
    print("=" * W)
    print("  PROMOTION RANK (discovery_score → promotion_score after family+grossDD discount)")
    print("=" * W)

    cols = ["strategy", "symbol", "family", "kelly_sharpe", "kelly_dd",
            "kelly_gross_dd", "kelly_roi", "kelly_pf", "family_rank",
            "gross_dd_disc", "family_disc", "promotion_score", "promoted"]
    existing = [c for c in cols if c in df.columns]
    disp = df[existing].head(40)

    hdr = (f'  {"Strategy":<22} {"Symbol":<12} {"Family":<12} '
           f'{"Sharpe":>7} {"MaxDD%":>8} {"GrossDD%":>9} {"ROI%":>7} '
           f'{"GDD_disc":>9} {"Fam_disc":>9} {"PromoScore":>11} {"Promoted":>8}')
    print(hdr)
    print("  " + "-" * (W-2))
    for _, r in disp.iterrows():
        promo_flag = "✅ YES" if r.get("promoted") else "   no"
        print(f'  {r["strategy"]:<22} {r["symbol"]:<12} {r["family"]:<12} '
              f'{r["kelly_sharpe"]:>7.3f} {r["kelly_dd"]:>8.1f} '
              f'{r.get("kelly_gross_dd", r["kelly_dd"]):>9.1f} '
              f'{r["kelly_roi"]:>7.1f} '
              f'{r["gross_dd_disc"]:>9.4f} {r["family_disc"]:>9.4f} '
              f'{r["promotion_score"]:>11.4f} {promo_flag:>8}')

    promoted = df[df["promoted"] == True]
    print(f'\n{"=" * W}')
    print(f'  Promoted set ({len(promoted)} strategies passing family+concentration caps):')
    for _, r in promoted.iterrows():
        print(f'    ✅  {r["strategy"]:<25} {r["symbol"]:<12} '
              f'PromoScore={r["promotion_score"]:.4f}  Sharpe={r["kelly_sharpe"]:.3f}  '
              f'MaxDD={r["kelly_dd"]:.1f}%  GrossDD={r.get("kelly_gross_dd", r["kelly_dd"]):.1f}%')
    print(f'{"=" * W}')
    print(f'Saved: {OUTPUT_CSV}')


if __name__ == "__main__":
    main()

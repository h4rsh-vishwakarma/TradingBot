"""
Generate Backtest CSVs (4H) for all strategies from tournament_winners_4h.csv.
Creates per-trade PnL CSVs in backtesting/A_Leaderboard/backtest_imports/
with filename pattern: {Strategy}_{Symbol}_4h_backtest.csv

Differences from the 15m version:
  - Reads tournament_winners_4h.csv
  - Loads {SYMBOL}_3y_4h.csv data files
  - ADX filter threshold: 20 (vs 25 for 15m)
  - Gap filter: min 2 bars between signals
  - Output filename suffix: _4h_backtest.csv
"""

import os, sys, pandas as pd, numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from my_strategies import apply_strategy, calculate_adx

DATA_DIR   = PROJECT_ROOT / "storage" / "backtest_data"
OUTPUT_DIR = PROJECT_ROOT / "backtesting" / "A_Leaderboard" / "backtest_imports"
REPORT_PATH = PROJECT_ROOT / "storage" / "reports" / "tournament_winners_4h.csv"

STOP_LOSS   = 0.02   # 2%
TAKE_PROFIT = 0.06   # 6%
ADX_THRESH  = 20
MIN_GAP     = 2      # minimum bars between signals


def apply_gap_filter(sig_series: pd.Series, min_gap: int) -> pd.Series:
    """Zero-out signals that fire within min_gap bars of the previous signal."""
    sig = sig_series.copy()
    last_sig_bar = -min_gap - 1
    for i in range(len(sig)):
        if sig.iloc[i] != 0:
            if i - last_sig_bar < min_gap:
                sig.iloc[i] = 0
            else:
                last_sig_bar = i
    return sig


def generate_trade_csv(symbol: str, strategy_name: str, mult: float, length: int) -> bool:
    """Generate a per-trade PnL CSV from 4H backtest data."""
    data_file = DATA_DIR / f"{symbol}_3y_4h.csv"
    if not data_file.exists():
        print(f"  Data file missing: {data_file}")
        return False

    df = pd.read_csv(data_file)
    df["pct"] = df["close"].pct_change()

    try:
        raw_sig = apply_strategy(df, strategy_name, True, mult, length)
        df["sig"] = raw_sig

        # ADX filter (threshold 20 for 4H)
        adx = calculate_adx(df, n=14)
        df["sig"] = np.where(adx > ADX_THRESH, df["sig"], 0)

        # Gap filter: min MIN_GAP bars between signals
        df["sig"] = apply_gap_filter(df["sig"], MIN_GAP)

        # Only keep bars where signal changes (new entry)
        sig_prev = df["sig"].shift(1).fillna(0)
        entry_mask = (df["sig"] != 0) & (df["sig"] != sig_prev)
        df["sig"] = np.where(entry_mask, df["sig"], 0)

        # Trade return: signal at bar t → return at bar t+1
        df["trade_ret"] = df["sig"] * df["pct"].shift(-1)
        df["trade_ret"] = df["trade_ret"].clip(lower=-STOP_LOSS, upper=TAKE_PROFIT)

    except Exception as e:
        print(f"  Strategy error: {e}")
        return False

    trades = df[df["sig"] != 0][["timestamp", "close", "sig", "trade_ret"]].copy()
    trades = trades.rename(columns={
        "timestamp": "Date",
        "close":     "Price",
        "sig":       "Side",
        "trade_ret": "Profit",
    })
    trades["Side"]   = trades["Side"].map({1: "Long", -1: "Short"})
    trades["Profit"] = (trades["Profit"] * 100).round(4)  # convert to %

    if trades.empty:
        print("  No trades generated")
        return False

    clean_name = (
        strategy_name
        .replace("'", "").replace('"', "").replace("[", "")
        .replace("]", "").replace(",", "").replace(" ", "_")[:50]
    )
    clean_sym = symbol.replace("USDT", "USD")
    filename  = f"{clean_name}_{clean_sym}_4h_backtest.csv"
    out_path  = OUTPUT_DIR / filename

    trades.to_csv(out_path, index=False)
    return True


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if not REPORT_PATH.exists():
        print(f"tournament_winners_4h.csv not found at {REPORT_PATH}")
        return

    df    = pd.read_csv(REPORT_PATH)
    total = len(df)
    success = 0

    print(f"Generating 4H backtest CSVs for {total} strategy-symbol combos...\n")

    for _, row in df.iterrows():
        symbol   = row["Symbol"]
        strategy = row["Strategy"]
        mult     = float(row.get("Optimal_Mult", 3.0))
        length   = int(row.get("Optimal_Len", 14))

        print(f"  [{symbol}] {strategy[:40]}...", end=" ")
        if generate_trade_csv(symbol, strategy, mult, length):
            print("OK")
            success += 1
        else:
            print("SKIP")

    print(f"\nDone: {success}/{total} CSVs written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()

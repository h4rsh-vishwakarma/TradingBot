#!/usr/bin/env python3
"""
P4: Vectorbt signal replay using real bot.log signal timestamps + Binance OHLCV.
No warmup issue, no Pine drift risk, uses actual prices on actual candles.
Run: source venv/bin/activate && python3 scripts/vbt_signal_replay.py
"""
import json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("BINANCE_TESTNET", "false")

BOT_LOG     = PROJECT_ROOT / "logs" / "bot.log"
OHLCV_CACHE = PROJECT_ROOT / "storage" / "backtest_data"
REPORT_OUT  = PROJECT_ROOT / "storage" / "backtest_results" / "vbt_signal_replay_20260423.csv"

SL_PCT = 0.01   # 1% stop loss  (from settings.json)
TP_PCT = 0.03   # 3% take profit


# ── 1. Extract signals from bot.log ──────────────────────────────────────────

SIGNAL_RE = re.compile(
    r'"timestamp":\s*"([^"]+)".*?"strategy":\s*"([^"]+)".*?"action":\s*"(buy|sell)".*?"ticker":\s*"([^"]+)".*?"price":\s*"([^"]+)"',
    re.DOTALL
)

def load_signals():
    signals = []
    if not BOT_LOG.exists():
        print(f"bot.log not found: {BOT_LOG}")
        return signals
    with open(BOT_LOG, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
                msg = rec.get("message", "")
                m = SIGNAL_RE.search(msg)
                if m:
                    ts, strategy, action, ticker, price = m.groups()
                    signals.append({
                        "timestamp": ts,
                        "strategy":  strategy,
                        "action":    action.upper(),
                        "symbol":    ticker.replace(".P", ""),
                        "price":     float(price),
                    })
            except Exception:
                pass
    print(f"Extracted {len(signals)} signals from bot.log")
    return signals


# ── 2. Pull OHLCV from Binance ────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, interval="4h", limit=500) -> pd.DataFrame:
    cache_file = OHLCV_CACHE / f"{symbol}_{interval}.csv"
    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=["open_time"])
        print(f"  Loaded {symbol} {interval} from cache ({len(df)} rows)")
        return df
    try:
        from binance.client import Client
        api_key    = os.getenv("BINANCE_API_KEY", "")
        api_secret = os.getenv("BINANCE_API_SECRET", "")
        c = Client(api_key, api_secret, testnet=False)
        raw = c.futures_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(raw, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"
        ])
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        OHLCV_CACHE.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file, index=False)
        print(f"  Fetched {symbol} {interval}: {len(df)} candles -> {cache_file}")
        return df
    except Exception as e:
        print(f"  ERROR fetching {symbol}: {e}")
        return pd.DataFrame()


# ── 3. Vectorbt replay ────────────────────────────────────────────────────────

def run_replay(signals, ohlcv_map):
    try:
        import vectorbt as vbt
    except ImportError:
        print("vectorbt not installed in current env — activate venv first")
        return pd.DataFrame()

    results = []
    grouped = {}
    for sig in signals:
        key = (sig["strategy"], sig["symbol"])
        grouped.setdefault(key, []).append(sig)

    for (strategy, symbol), sigs in grouped.items():
        df = ohlcv_map.get(symbol)
        if df is None or df.empty:
            print(f"  SKIP {strategy}/{symbol} — no OHLCV")
            continue

        df = df.set_index("open_time").sort_index()
        close = df["close"]

        entries  = pd.Series(False, index=close.index)
        exits    = pd.Series(False, index=close.index)

        for sig in sigs:
            try:
                ts = pd.Timestamp(sig["timestamp"]).tz_localize("UTC") if pd.Timestamp(sig["timestamp"]).tzinfo is None else pd.Timestamp(sig["timestamp"])
                nearest = close.index[close.index.get_indexer([ts], method="nearest")[0]]
                if sig["action"] == "BUY":
                    entries[nearest] = True
                else:
                    exits[nearest] = True
            except Exception:
                pass

        if not entries.any():
            print(f"  SKIP {strategy}/{symbol} — no entries aligned")
            continue

        try:
            pf = vbt.Portfolio.from_signals(
                close,
                entries=entries,
                exits=exits,
                sl_stop=SL_PCT,
                tp_stop=TP_PCT,
                fees=0.001,
                freq="4h",
            )
            stats = pf.stats()
            results.append({
                "strategy":    strategy,
                "symbol":      symbol,
                "total_trades": int(stats.get("Total Trades", 0)),
                "win_rate":    round(float(stats.get("Win Rate [%]", 0)), 2),
                "total_return": round(float(stats.get("Total Return [%]", 0)), 4),
                "sharpe":      round(float(stats.get("Sharpe Ratio", 0)), 4),
                "max_dd":      round(float(stats.get("Max Drawdown [%]", 0)), 4),
                "profit_factor": round(
                    float(stats.get("Gross Profit", 0)) / max(abs(float(stats.get("Gross Loss", -1e-9))), 1e-9), 4
                ),
            })
            print(f"  OK  {strategy}/{symbol}  trades={results[-1]['total_trades']}  return={results[-1]['total_return']}%")
        except Exception as e:
            print(f"  ERROR  {strategy}/{symbol}: {e}")

    return pd.DataFrame(results)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    signals = load_signals()
    if not signals:
        print("No signals extracted. Check bot.log path.")
        return

    symbols = list({s["symbol"] for s in signals})
    print(f"\nFetching OHLCV for {len(symbols)} symbols: {symbols}")
    ohlcv_map = {}
    for sym in symbols:
        df = fetch_ohlcv(sym)
        if not df.empty:
            ohlcv_map[sym] = df

    print(f"\nRunning vectorbt replay on {len(signals)} signals...")
    results = run_replay(signals, ohlcv_map)

    if results.empty:
        print("No results produced.")
        return

    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(REPORT_OUT, index=False)
    print(f"\n=== REPLAY RESULTS ===")
    print(results.to_string(index=False))
    print(f"\nSaved to {REPORT_OUT}")


if __name__ == "__main__":
    main()

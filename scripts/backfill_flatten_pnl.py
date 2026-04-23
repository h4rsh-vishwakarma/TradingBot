#!/usr/bin/env python3
# P3: Backfill flatten PnL from Binance testnet for LINKUSDT/SUIUSDT/LDOUSDT Apr 22 2026
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("BINANCE_TESTNET", "true")

SYMBOLS = {
    "LINKUSDT": "G94 Pivot Point Reclaim",
    "SUIUSDT":  "G95 Inside Bar Breakout",
    "LDOUSDT":  "G91 ATR Compression Breakout",
}

APR22_START = int(datetime(2026, 4, 22, 0, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
APR22_END   = int(datetime(2026, 4, 22, 23, 59, 59, tzinfo=timezone.utc).timestamp() * 1000)
LEDGER      = PROJECT_ROOT / "logs" / "trades.jsonl"


def main():
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    client = BinanceClient()
    backfilled = []

    for symbol, strategy in SYMBOLS.items():
        print(f"\n=== {symbol} ({strategy}) ===")
        try:
            trades = client.client.futures_account_trades(
                symbol=symbol, startTime=APR22_START, endTime=APR22_END
            )
        except Exception as e:
            print(f"  ERROR fetching trades: {e}")
            continue

        if not trades:
            print("  No testnet trades found for Apr 22 window")
            continue

        realized_pnl = sum(float(t.get("realizedPnl", 0)) for t in trades)
        qty_total    = sum(abs(float(t.get("qty", 0))) for t in trades)
        last_ts      = max(int(t["time"]) for t in trades)
        ts_str       = datetime.utcfromtimestamp(last_ts / 1000).isoformat()

        print(f"  Trades found : {len(trades)}")
        print(f"  Realized PnL : {realized_pnl:.4f} USDT")
        print(f"  Qty total    : {qty_total}")
        print(f"  Last trade   : {ts_str}")

        rec = {
            "timestamp":        ts_str,
            "action":           "position_closed",
            "symbol":           symbol,
            "side":             "flatten",
            "qty":              qty_total,
            "pnl":              round(realized_pnl, 6),
            "strategy":         strategy,
            "close_reason":     "flatten",
            "ledger_source":    "backfill_testnet_Apr22",
            "raw_trade_count":  len(trades),
        }
        backfilled.append(rec)

    if not backfilled:
        print("\nNo trades to backfill — nothing written.")
        return

    print(f"\nWriting {len(backfilled)} entries to {LEDGER}")
    with open(LEDGER, "a") as f:
        for rec in backfilled:
            f.write(json.dumps(rec) + "\n")
            print(f"  WRITTEN: {rec['symbol']}  pnl={rec['pnl']}")

    print("\nDone. Verify with: tail -5 logs/trades.jsonl")


if __name__ == "__main__":
    main()

"""Download 5Y 4H OHLCV from Binance Futures API (fapi.binance.com).
Replaces spot data — futures bars are the correct source for our testnet strategies.
"""
import json
import time
import urllib.request
import datetime
from pathlib import Path

DATA_DIR = Path("/home/ubuntu/tradingview_webhook_bot/storage/backtest_data")
ASSETS = [
    "ETHUSDT", "BTCUSDT", "SOLUSDT", "LDOUSDT", "SUIUSDT",
    "OPUSDT",  "AVAXUSDT", "LINKUSDT", "BNBUSDT", "XRPUSDT",
]


def download_futures_5y(symbol: str) -> None:
    out    = DATA_DIR / f"{symbol}_5y_4h.csv"
    backup = DATA_DIR / f"{symbol}_5y_4h_spot_backup.csv"
    print(f"  [{symbol}] fetching from Binance Futures...", flush=True)

    rows: list = []
    end_ms = int(time.time() * 1000)

    for _ in range(14):  # 14 x 1000 bars = 14 000 bars (~5.2 years)
        url = (
            f"https://fapi.binance.com/fapi/v1/klines"
            f"?symbol={symbol}&interval=4h&limit=1000&endTime={end_ms}"
        )
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                batch = json.loads(resp.read())
        except Exception as exc:
            print(f"    [{symbol}] request error: {exc}", flush=True)
            break
        if not batch:
            break
        rows = batch + rows
        end_ms = batch[0][0] - 1
        if len(batch) < 1000:
            break
        time.sleep(0.12)

    if not rows:
        print(f"  [{symbol}] ERROR — no futures data returned", flush=True)
        return

    # Back up existing spot file
    if out.exists():
        out.rename(backup)

    header = "timestamp,open,high,low,close,volume"
    lines = [header]
    for r in rows:
        ts = datetime.datetime.utcfromtimestamp(int(r[0]) / 1000).strftime("%Y-%m-%d %H:%M:%S+00:00")
        lines.append(f"{ts},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]}")
    out.write_text("\n".join(lines))

    first_dt = datetime.datetime.utcfromtimestamp(int(rows[0][0]) / 1000).strftime("%Y-%m-%d")
    last_dt  = datetime.datetime.utcfromtimestamp(int(rows[-1][0]) / 1000).strftime("%Y-%m-%d")
    print(f"  [{symbol}] {len(rows)} bars | {first_dt} -> {last_dt} | saved", flush=True)


if __name__ == "__main__":
    for sym in ASSETS:
        download_futures_5y(sym)
    print("\nAll done. Old spot files backed up as *_spot_backup.csv")

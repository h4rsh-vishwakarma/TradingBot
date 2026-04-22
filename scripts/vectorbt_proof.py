"""
vectorbt syslog proof — runs a real EMA crossover backtest on ETHUSDT 4H data
and writes results to syslog + a proof log file.
Run: venv/bin/python3 scripts/vectorbt_proof.py
"""
import sys, os, syslog, datetime

sys.path.insert(0, "/home/ubuntu/tradingview_webhook_bot")

PROOF_LOG = "/home/ubuntu/tradingview_webhook_bot/storage/reports/vectorbt_proof.log"
DATA_FILE = "/home/ubuntu/tradingview_webhook_bot/storage/backtest_data/ETHUSDT_3y_4h.csv"

def run():
    import pandas as pd
    import vectorbt as vbt

    ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    syslog.openlog("tradingbot-vectorbt", syslog.LOG_PID, syslog.LOG_USER)

    syslog.syslog(syslog.LOG_INFO, f"vectorbt proof started | version={vbt.__version__} | data={DATA_FILE}")

    df = pd.read_csv(DATA_FILE, parse_dates=["timestamp"])
    df.set_index("timestamp", inplace=True)
    close = df["close"]

    # EMA 9/21 crossover — simple proof-of-concept
    fast = close.ewm(span=9, adjust=False).mean()
    slow = close.ewm(span=21, adjust=False).mean()
    entries = (fast > slow) & (fast.shift() <= slow.shift())
    exits   = (fast < slow) & (fast.shift() >= slow.shift())

    pf = vbt.Portfolio.from_signals(
        close, entries, exits,
        init_cash=1000.0, fees=0.0004, sl_stop=0.03,
    )

    total_return = round(pf.total_return() * 100, 2)
    sharpe = round(float(pf.sharpe_ratio()), 3)
    n_trades = int(pf.trades.count())
    win_rate = round(float(pf.trades.win_rate()) * 100, 1)
    max_dd = round(float(pf.max_drawdown()) * 100, 2)

    result_line = (
        f"[{ts}] vectorbt={vbt.__version__} | ETHUSDT 4H EMA9/21 | "
        f"n_trades={n_trades} | WR={win_rate}% | total_return={total_return}% | "
        f"sharpe={sharpe} | max_dd={max_dd}%"
    )

    print(result_line)
    syslog.syslog(syslog.LOG_INFO, f"vectorbt proof result: {result_line}")
    syslog.closelog()

    os.makedirs(os.path.dirname(PROOF_LOG), exist_ok=True)
    with open(PROOF_LOG, "a") as f:
        f.write(result_line + "\n")

    print(f"Proof written to: {PROOF_LOG}")
    return result_line

if __name__ == "__main__":
    run()

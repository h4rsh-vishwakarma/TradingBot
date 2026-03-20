import os, sys, json, pandas as pd, html, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Path setup
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load Env Vars
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity

def dispatch_top_strategies(force=False):
    telegram = TelegramAlert()
    report_path = os.path.join(PROJECT_ROOT, "storage/reports/tournament_winners.csv")

    try:
        df = pd.read_csv(report_path)
        # 🔥 Sabhi strategies (No limits)
        targets = df[df['Daily_ROI_%'] >= 1.2].sort_values(by='Daily_ROI_%', ascending=False)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # Header message
    status_msg = (f"🚀 <b>UNLIMITED ALPHA MODE V5.5</b> 🚀\n\n"
                  f"📊 Found: <b>{len(targets)}</b> strategies.\n"
                  f"⚡ Target: >1.2% Daily ROI\n"
                  f"🕒 Status: Sequential Dispatching Started...")
    telegram.send(severity=AlertSeverity.INFO, title="Alpha Engine", message=status_msg)
    time.sleep(3) 

    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        mult = winner.get('Optimal_Mult', 3.0)
        length = int(winner.get('Optimal_Len', 14))
        roi = winner.get('Daily_ROI_%', 0.0)
        dd = winner.get('Max_DD_%', 0.0)

        # Logic Mapping
        if any(k in strat.upper() for k in ["SMC", "LIQUIDITY", "FLOW"]):
            core_logic = f"lookback = {length}\nlong = close > close[lookback]\nshort = close < close[lookback]"
        elif any(k in strat.upper() for k in ["SQUEEZE", "REVERSION", "ML", "LORENTZIAN"]):
            core_logic = f"basis = ta.sma(close, {length})\ndev = {mult} * ta.stdev(close, {length})\nlong = close < basis - dev\nshort = close > basis + dev"
        else:
            core_logic = f"[st, dir] = ta.supertrend({mult}, {length})\nlong = ta.crossover(close, st)\nshort = ta.crossunder(close, st)"

        pine_code = f"""//@version=5
strategy("AI {symbol} Rank{i+1}", overlay=true, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=10)
// Strategy: {strat}
{core_logic}
start_time = timestamp(2023, 01, 01, 00, 00)
if (time >= start_time)
    if long
        strategy.entry("Long", strategy.long, comment='{{"ROI": "{roi}%"}}')
    if short
        strategy.entry("Short", strategy.short, comment='{{"ROI": "{roi}%"}}')
"""
        safe_code = html.escape(pine_code)
        
        # 1. Stats Message
        msg = (f"🏆 <b>RANK #{i+1} WINNER</b> 🏆\n"
               f"📊 Symbol: {symbol}\n"
               f"🧠 Strategy: {strat}\n"
               f"📈 Daily ROI: {roi}%\n"
               f"📉 Max DD: {dd}%")

        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Stats", message=msg)
        time.sleep(2) # ⚡ Increased delay for delivery assurance
        
        # 2. Pine Code Message
        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Code", message=f"<code>{safe_code}</code>")
        
        # 🔥 BATCH COOLING (Bypasses Telegram Flood Wait)
        # Har 3 strategies ke baad 5 second ka pause, aur har 10 ke baad 10 second.
        if (i + 1) % 10 == 0:
            print(f"🛑 Major Cool-down after {i+1}th strategy...")
            time.sleep(10)
        elif (i + 1) % 3 == 0:
            time.sleep(4)
        else:
            time.sleep(2)

    print(f"✅ Unlimited Dispatch Complete. Total sent: {len(targets)}")

if __name__ == "__main__":
    dispatch_top_strategies(force=True)

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
        targets = df[df['Daily_ROI_%'] >= 1.2].sort_values(by='Daily_ROI_%', ascending=False)
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # Header Message
    telegram.send(severity=AlertSeverity.INFO, title="Alpha Engine v9.0 [GOD MODE]", 
                  message=f"🛡️ <b>PERMANENT ERROR BYPASS ACTIVE</b>\nDeploying {len(targets)} scripts with Zero-Margin logic.")
    time.sleep(2)

    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        mult = winner.get('Optimal_Mult', 3.0)
        length = int(winner.get('Optimal_Len', 14))
        roi = round(float(winner.get('Daily_ROI_%', 0.0)), 3)
        dd = round(float(winner.get('Max_DD_%', 0.0)), 2)

        # 🎯 Logic Injection
        if any(k in strat.upper() for k in ["SMC", "LIQUIDITY", "FLOW", "BARUPDN"]):
             core_logic = f"lookback = {length}\nlong = close > close[lookback]\nshort = close < close[lookback]"
        elif any(k in strat.upper() for k in ["SUPERTREND"]):
             core_logic = f"[st, dir] = ta.supertrend({mult}, {length})\nlong = ta.crossover(close, st)\nshort = ta.crossunder(close, st)"
        else:
             core_logic = f"basis = ta.sma(close, {length})\ndev = {mult} * ta.stdev(close, {length})\nlong = close < basis - dev\nshort = close > basis + dev"

        # 🔥 THE "GOD MODE" TEMPLATE (No Equity Dependency)
        pine_code = f"""//@version=5
strategy("AI {symbol} Rank{i+1}", overlay=true, initial_capital=100000000, currency=currency.USD, margin_long=0, margin_short=0)

// --- Strategy Logic ---
{core_logic}

// --- 🛡️ Zero-Error Execution Engine ---
// Hum fixed qty use kar rahe hain taaki TV engine crash na ho
fixed_qty = 10
start_time = timestamp(2024, 01, 01, 00, 00)

if (time >= start_time)
    if long
        strategy.entry("Long", strategy.long, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
    if short
        strategy.entry("Short", strategy.short, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
"""
        safe_code = html.escape(pine_code)
        
        # Telegram Dispatch
        msg = (f"🏆 <b>RANK #{i+1} WINNER</b> 🏆\n"
               f"📊 Symbol: {symbol}\n"
               f"📈 Daily ROI: {roi}%\n"
               f"📉 Max DD: {dd}% (Protected)")

        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Stats", message=msg)
        time.sleep(1.5)
        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} [SECURE] Code", message=f"<code>{safe_code}</code>")
        
        print(f"✅ Dispatched {symbol} Rank #{i+1} in God Mode.")
        time.sleep(2)

if __name__ == "__main__":
    dispatch_top_strategies(force=True)

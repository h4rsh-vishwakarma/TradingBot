import os, sys, pandas as pd
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# --- SET PATHS ---
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

# Path Injection
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))
from scripts.strategy_tournament import strategy_tournament
from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity

def run_full_automation():
    print(f"🌅 Starting Automated Alpha Scan...")
    telegram = TelegramAlert()
    
    # 1. Update Leaderboard
    try:
        strategy_tournament()
    except Exception as e:
        print(f"Tournament Error: {e}"); return

    # 2. Read Results
    report_path = '/home/ubuntu/tradingview_webhook_bot/storage/reports/tournament_winners.csv'
    if not os.path.exists(report_path): return

    df = pd.read_csv(report_path)
    winner = df.iloc[0] 
    
    # Clean data for message
    sym = winner['Symbol']
    strat = winner['Strategy']
    daily = winner['Daily_%']
    tier = winner['Tier']

    # 3. Pine Code
    pine_code = f"//@version=5\nstrategy('AI_{strat[:10]}', overlay=true)\nema200 = ta.ema(close, 200)\nadx = ta.adx(14)\nlong = (close > ema200) and (adx > 25)\nif long\n    strategy.entry('Long', strategy.long)\nstrategy.exit('Exit', stop=close*0.975, limit=close*1.075)"

    # 4. Message (HTML Format for Stability)
    msg = (f"<b>🏆 WINNER STRATEGY FOUND</b>\n\n"
           f"📊 <b>Symbol:</b> {sym}\n"
           f"🧠 <b>Strategy:</b> {strat}\n"
           f"📈 <b>Daily:</b> {daily}%\n"
           f"🏅 <b>Tier:</b> {tier}\n\n"
           f"🚀 <b>Optimized Pine Script:</b>\n"
           f"<code>{pine_code}</code>")

    try:
        telegram.send(severity=AlertSeverity.INFO, title="Daily Alpha Report", message=msg)
        print("✅ Message successfully sent to Telegram!")
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

if __name__ == "__main__":
    run_full_automation()

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
    print(f"Starting Automated Alpha Scan...")
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
    top5 = df.head(5)

    # 3. Build summary message with all new columns
    lines = ["<b>DAILY ALPHA REPORT</b>\n"]
    for i, row in top5.iterrows():
        sym = row['Symbol']
        strat = str(row['Strategy'])[:35]
        daily_roi = round(row.get('Daily_ROI_%', 0), 3)
        gross_dd = round(row.get('Gross_DD_%', row.get('Max_DD_%', 0)), 2)
        net_dd = round(row.get('Net_DD_%', gross_dd), 2)
        win_rate = round(row.get('Win_Rate_%', 0), 1)
        sharpe = round(row.get('Sharpe_Ratio', 0), 2)
        tier = row.get('Tier', 'N/A')

        lines.append(
            f"<b>#{i+1}</b> {tier} | {sym}\n"
            f"   {strat}\n"
            f"   ROI: <code>{daily_roi}%</code>/day\n"
            f"   Gross DD: <code>{gross_dd}%</code> | Net DD: <code>{net_dd}%</code>\n"
            f"   Win: <code>{win_rate}%</code> | Sharpe: <code>{sharpe}</code>\n"
        )

    msg = "\n".join(lines)

    try:
        telegram.send(severity=AlertSeverity.INFO, title="Daily Alpha Report", message=msg)
        print("Message successfully sent to Telegram!")
    except Exception as e:
        print(f"Telegram Error: {e}")

if __name__ == "__main__":
    run_full_automation()

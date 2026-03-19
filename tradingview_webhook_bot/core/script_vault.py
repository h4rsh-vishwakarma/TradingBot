import os, sys, json, pandas as pd, html, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# --- 1. DYNAMIC PATH RESOLUTION ---
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load Env Vars
ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)

from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity

# File to track the last run date
LAST_RUN_FILE = "/tmp/last_alpha_run.txt"

def dispatch_top_strategies(force=False):
    """
    Dispatches Top 5 Alpha/Average strategies with scaling fixes.
    force=True ignores the daily cooldown.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    telegram = TelegramAlert()

    # --- 🛡️ 1. DAILY COOLDOWN CHECK ---
    if not force and os.path.exists(LAST_RUN_FILE):
        with open(LAST_RUN_FILE, "r") as f:
            if f.read().strip() == today_str:
                print("⚠️ Already dispatched today. Skipping automatic run.")
                return

    report_path = os.path.join(PROJECT_ROOT, "storage/reports/tournament_winners.csv")
    template_path = os.path.join(PROJECT_ROOT, "templates/supertrend_base.txt")

    if not os.path.exists(report_path):
        print(f"❌ Leaderboard missing: {report_path}")
        return

    # --- 🧠 2. DATA PROCESSING ---
    try:
        df = pd.read_csv(report_path)
    except Exception as e:
        print(f"❌ Error reading CSV: {e}")
        return

    # Filter ALPHA and AVERAGE Tiers
    alpha_df = df[df['Tier'].str.contains("ALPHA", na=False)]
    average_df = df[df['Tier'].str.contains("AVERAGE", na=False)]
    
    # Combine and pick Top 5
    targets = pd.concat([alpha_df, average_df]).head(5)

    if targets.empty:
        telegram.send(severity=AlertSeverity.WARNING, title="No Strategy", message="⚠️ Unstable Market: No Alpha/Average strategies found.")
        return

    # Initial status message
    status_msg = "🚀 <b>System Update:</b> Generating Alpha-Ready Pine Scripts with Garima's Scaling Fixes (Max Bars & Pyramiding)..."
    telegram.send(severity=AlertSeverity.INFO, title="Alpha Discovery", message=status_msg)

    # --- 🚀 3. SCRIPT GENERATION & SEQUENTIAL DISPATCH ---
    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        
        if os.path.exists(template_path):
            with open(template_path, 'r') as f:
                raw_code = f.read()
                # Injecting Parameters into Template
                code = raw_code.replace("{{SYMBOL}}", symbol).replace("{{STRAT}}", strat)
                code = code.replace("{{MULT}}", "3.0").replace("{{LEN}}", "10")

            # Escape HTML characters to prevent Telegram HTTP 400 errors
            safe_code = html.escape(code)

            # Prepare Stats Message
            msg = (f"🏆 <b>RANK #{i+1} WINNER</b> 🏆\n\n"
                   f"🏅 <b>Tier:</b> {winner['Tier']}\n"
                   f"📊 <b>Symbol:</b> {symbol}\n"
                   f"🧠 <b>Strategy:</b> {strat}\n"
                   f"📈 1Y ROI: <b>{winner['Daily_%']}%</b>\n"
                   f"📉 Max DD: <b>{winner['Max_DD_%']}%</b>")

            # Sequential Send with small delay to prevent API Flood/Limit issues
            try:
                # 1. Send Stats
                telegram.send(severity=AlertSeverity.INFO, title=f"Winner #{i+1} Stats", message=msg)
                time.sleep(0.5) # Short buffer
                
                # 2. Send Code Block (Separate message to ensure delivery)
                telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Pine Code", message=f"<code>{safe_code}</code>")
                time.sleep(1.0) # Longer buffer between winners
                
                print(f"✅ Dispatched Rank #{i+1}: {symbol} {strat}")
            except Exception as e:
                print(f"❌ Failed to send Rank #{i+1}: {e}")
        else:
            print(f"❌ Template missing at {template_path}")

    # Update the cooldown file
    with open(LAST_RUN_FILE, "w") as f:
        f.write(today_str)

    print(f"✅ Full Dispatch Complete. Top {len(targets)} strategies sent.")

if __name__ == "__main__":
    # Force=True allows manual command overrides via Telegram Listener
    dispatch_top_strategies(force=True)

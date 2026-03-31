import os, sys, time, subprocess, sqlite3
import pandas as pd
import telebot
from pathlib import Path
from dotenv import load_dotenv

# Path Setup
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ENV_VARS_PATH = "/etc/tradingbot/env_vars"
if os.path.exists(ENV_VARS_PATH):
    load_dotenv(dotenv_path=ENV_VARS_PATH, override=True)
else:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
DB_PATH = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/idempotency.db")
REPORT_PATH = os.path.join(PROJECT_ROOT, "storage/reports/tournament_winners.csv")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://127.0.0.1:5000/webhook/tradingview")

bot = telebot.TeleBot(TOKEN)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /help — Full Command Reference
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['help', 'start'])
def cmd_help(message):
    help_text = (
        "🤖 <b>Alpha Engine v10.0 — Command Center</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

        "🚀 <b>/alpha</b>\n"
        "   Deploy top Alpha++ strategies to Telegram.\n"
        "   Pine Script + Stats (ROI, Gross DD, Net DD).\n"
        "   Auto-runs daily 9 AM UTC via cron.\n\n"

        "📊 <b>/status</b>\n"
        "   Live system health: Net Profit, Trade Count,\n"
        "   Active Strategy, Node IP.\n\n"

        "🔍 <b>/audit</b>\n"
        "   Tournament Leaderboard — Top 10 strategies\n"
        "   with Daily ROI%, Gross DD, Net DD, Tier.\n\n"

        "💹 <b>/buy SYMBOL</b>\n"
        "   Manual BUY signal. Example: <code>/buy SOLUSDT</code>\n"
        "   Sends to orchestrator for execution.\n\n"

        "💹 <b>/sell SYMBOL</b>\n"
        "   Manual SELL signal. Example: <code>/sell ETHUSDT</code>\n\n"

        "⚡ <b>/override SYMBOL</b>\n"
        "   Force BUY override (bypasses tier check).\n"
        "   Example: <code>/override BTCUSDT</code>\n\n"

        "🛡️ <b>/help</b>\n"
        "   Show this command reference.\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Institutional Updates v10.0:</b>\n"
        "• <b>DD Split:</b> Gross DD (compounding) + Net DD (fixed size).\n"
        "• <b>DD Reduction:</b> ADX &gt; 25 Filter + 4% Trailing Stop.\n"
        "• <b>God Mode:</b> $100M buffer (No TV Crashes).\n"
        "• <b>Blocked Trades:</b> Auto-logged to Google Sheets.\n"
        "• <b>Data Sync:</b> Trade files synced to GitHub daily."
    )
    bot.reply_to(message, help_text, parse_mode='HTML')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /status — Live System Stats
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['status'])
def cmd_status(message):
    net, count, strat = 0.0, 0, "System Ready"
    try:
        if os.path.exists(DB_PATH):
            conn = sqlite3.connect(DB_PATH)
            df_stats = pd.read_sql_query("SELECT SUM(realized_pnl) as net, COUNT(*) as cnt FROM trades", conn)
            df_strat = pd.read_sql_query("SELECT strategy_name FROM trades ORDER BY timestamp DESC LIMIT 1", conn)
            conn.close()
            net = round(df_stats['net'].iloc[0] or 0.0, 2)
            count = df_stats['cnt'].iloc[0] or 0
            strat = df_strat['strategy_name'].iloc[0] if not df_strat.empty else "Waiting for Signal"
    except Exception:
        pass

    msg = (f"📊 <b>SYSTEM STATUS: ACTIVE</b>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"🤖 <b>Strategy:</b> <code>{strat}</code>\n"
           f"💰 <b>Net Profit:</b> <code>${net} USDT</code>\n"
           f"🔄 <b>Total Trades:</b> <code>{count}</code>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"🟢 <b>System:</b> <code>Operational</code>\n"
           f"🕒 <b>Uptime:</b> <code>Active</code>")
    bot.send_message(message.chat.id, msg, parse_mode='HTML')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /alpha — Deploy Top Strategies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['alpha'])
def cmd_alpha(message):
    bot.reply_to(message, "🚀 <b>Deploying Alpha Strategies...</b>\nPine Scripts incoming.", parse_mode='HTML')
    subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tradingview_webhook_bot/core/script_vault.py")],
        cwd=str(PROJECT_ROOT)
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /audit — Tournament Leaderboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['audit'])
def cmd_audit(message):
    if not os.path.exists(REPORT_PATH):
        bot.reply_to(message, "⚠️ No tournament report found. Run backtest first.", parse_mode='HTML')
        return

    try:
        df = pd.read_csv(REPORT_PATH).head(10)
        lines = ["🔍 <b>Tournament Leaderboard — Top 10</b>\n━━━━━━━━━━━━━━━━━━"]

        for i, row in df.iterrows():
            symbol = row['Symbol']
            strat = str(row['Strategy'])[:35]
            roi = round(row['Daily_ROI_%'], 3)
            gross_dd = round(row.get('Gross_DD_%', row.get('Max_DD_%', 0)), 2)
            net_dd = round(row.get('Net_DD_%', gross_dd), 2)
            tier = row.get('Tier', 'N/A')
            win_rate = round(row.get('Win_Rate_%', 0), 1)
            sharpe = round(row.get('Sharpe_Ratio', 0), 2)
            total_trades = int(row.get('Total_Trades', 0))
            params_str = f"Mult: {round(float(row.get('Optimal_Mult', 0)), 2)} | Len: {int(row.get('Optimal_Len', 0))}"
            gdd_date = row.get('Gross_DD_Date', 'N/A')
            ndd_date = row.get('Net_DD_Date', 'N/A')
            gdd_cap = row.get('Gross_DD_Capital_Left', None)
            ndd_cap = row.get('Net_DD_Capital_Left', None)
            gdd_cap_str = f"${gdd_cap:,.0f}" if gdd_cap is not None and str(gdd_cap) not in ('', 'nan') else "N/A"
            ndd_cap_str = f"${ndd_cap:,.0f}" if ndd_cap is not None and str(ndd_cap) not in ('', 'nan') else "N/A"

            lines.append(
                f"\n<b>#{i+1}</b> {tier}\n"
                f"   <b>Symbol:</b> {symbol} | <b>Strategy:</b> {strat}\n"
                f"   📈 <b>Daily ROI:</b> <code>{roi}%</code>/day\n"
                f"   📉 <b>Gross DD:</b> <code>{gross_dd}%</code> (Compounding) | Date: {gdd_date} | Capital Left: {gdd_cap_str}\n"
                f"   📉 <b>Net DD:</b> <code>{net_dd}%</code> (Fixed Size) | Date: {ndd_date} | Capital Left: {ndd_cap_str}\n"
                f"   🎯 <b>Win Rate:</b> <code>{win_rate}%</code> | <b>Sharpe:</b> <code>{sharpe}</code>\n"
                f"   🔄 <b>Total Trades:</b> <code>{total_trades}</code>\n"
                f"   ⚙️ <b>Params:</b> {params_str}\n"
                f"   🛡️ <b>ADX &gt; 25:</b> ON | <b>Trailing Stop:</b> 4%"
            )

        bot.send_message(message.chat.id, "\n".join(lines), parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error reading report: {e}", parse_mode='HTML')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /buy, /sell, /override — Manual Trades
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['buy', 'sell', 'override'])
def cmd_trade(message):
    args = message.text.split()
    cmd = args[0].replace('/', '').lower()

    if len(args) < 2:
        bot.reply_to(message, f"❌ <b>Usage:</b> <code>/{cmd} SYMBOL</code>\nExample: <code>/{cmd} SOLUSDT</code>", parse_mode='HTML')
        return

    symbol = args[1].upper()
    action = "buy" if cmd in ["buy", "override"] else "sell"
    ts = time.strftime('%H:%M:%S')

    import requests
    payload = {
        "secret": WEBHOOK_SECRET,
        "passphrase": WEBHOOK_SECRET,
        "strategy": "multi_strategy",
        "strategy_id": "multi_strategy",
        "symbol": symbol,
        "ticker": symbol,
        "side": action,
        "action": action,
        "type": "market",
        "price": 0,
        "quantity": 0.005,
        "qty": 0.005,
        "timeframe": "1h",
        "indicator": "Manual_Override"
    }

    try:
        response = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if response.status_code == 200:
            msg = (f"⚡ <b>MANUAL SIGNAL EXECUTED</b>\n"
                   f"━━━━━━━━━━━━━━━━━━\n"
                   f"🔹 <b>Action:</b> <code>{action.upper()}</code>\n"
                   f"🔹 <b>Asset:</b> <code>{symbol}</code>\n"
                   f"🕒 <b>Time:</b> <code>{ts}</code>\n"
                   f"━━━━━━━━━━━━━━━━━━\n"
                   f"✅ <i>Order accepted by Orchestrator</i>")
            bot.send_message(message.chat.id, msg, parse_mode='HTML')
        else:
            bot.send_message(message.chat.id, f"❌ <b>FAILED</b>\nStatus: {response.status_code}\n{response.text}", parse_mode='HTML')
    except Exception as e:
        bot.send_message(message.chat.id, f"📡 <b>HUB OFFLINE</b>\n{e}", parse_mode='HTML')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    print("🛰️ Telegram Listener Active — All commands: /help /alpha /status /audit /buy /sell /override")
    bot.infinity_polling()

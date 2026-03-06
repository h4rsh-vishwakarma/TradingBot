import telebot, sqlite3, pandas as pd, os, requests, json, time, subprocess

# --- CONFIG ---
TOKEN = "7709465703:AAG049m19b8J0SFwCoHtkyRAnveynLSNPZo"
WEBHOOK_SECRET = "squeeze_tradingview_cluster_2026_secure"
DB_PATH = os.path.expanduser("~/tradingview_webhook_bot/storage/idempotency.db")

def get_docker_ip():
    try:
        return subprocess.getoutput("docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' tradingview_webhook_bot-orchestrator-1")
    except:
        return "172.19.0.2"

DOCKER_IP = get_docker_ip()
WEBHOOK_URL = f"http://{DOCKER_IP}:5000/webhook/tradingview"
bot = telebot.TeleBot(TOKEN)

def get_real_stats():
    if not os.path.exists(DB_PATH):
        return 0.0, 0, "Initial Sync..."
    try:
        conn = sqlite3.connect(DB_PATH)
        df_stats = pd.read_sql_query("SELECT SUM(realized_pnl) as net, COUNT(*) as cnt FROM trades", conn)
        df_strat = pd.read_sql_query("SELECT strategy_name FROM trades ORDER BY timestamp DESC LIMIT 1", conn)
        conn.close()
        
        net = round(df_stats['net'].iloc[0] or 0.0, 2)
        count = df_stats['cnt'].iloc[0] or 0
        strat = df_strat['strategy_name'].iloc[0] if not df_strat.empty else "Waiting for Signal"
        return net, count, strat
    except:
        return 0.0, 0, "System Ready"

@bot.message_handler(commands=['status'])
def cmd_status(message):
    net, count, strat = get_real_stats()
    msg = (f"📊 <b>SYDNEY HUB STATUS: ACTIVE</b>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"🤖 <b>Strategy:</b> <code>{strat}</code>\n"
           f"💰 <b>Net Profit:</b> <code>${net} USDT</code>\n"
           f"🔄 <b>Total Trades:</b> <code>{count}</code>\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"🟢 <b>System:</b> <code>Operational</code>\n"
           f"📡 <b>Node:</b> <code>{DOCKER_IP}</code>")
    bot.send_message(message.chat.id, msg, parse_mode='HTML')

@bot.message_handler(commands=['buy', 'sell', 'override'])
def handle_trade(message):
    args = message.text.split()
    cmd = args[0].replace('/', '').lower()
    if len(args) < 2:
        bot.reply_to(message, "❌ <b>Usage:</b> <code>/buy SYMBOL</code>", parse_mode='HTML')
        return

    symbol = args[1].upper()
    action = "buy" if cmd in ["buy", "override"] else "sell"
    strat_name = "Manual_Hub"
    ts = time.strftime('%H:%M:%S')
    
    # 🚨 RESTORING THE 100% WORKING SCHEMA 🚨
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
                   f"🔹 <b>Strategy:</b> <code>{strat_name}</code>\n"
                   f"🕒 <b>Time:</b> <code>{ts}</code>\n"
                   f"━━━━━━━━━━━━━━━━━━\n"
                   f"✅ <i>Order accepted by Orchestrator</i>")
            bot.send_message(message.chat.id, msg, parse_mode='HTML')
        else:
            bot.send_message(message.chat.id, f"❌ <b>EXECUTION FAILED</b>\nStatus: {response.status_code}\nResp: {response.text}")
    except Exception as e:
        bot.send_message(message.chat.id, f"📡 <b>HUB OFFLINE</b>\n{e}")

if __name__ == "__main__":
    bot.infinity_polling()

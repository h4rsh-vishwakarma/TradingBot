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

        "🚀 <b>/alpha</b> — Deploy all ALPHA scripts to Telegram\n"
        "📊 <b>/winners</b> — Quick leaderboard summary (all tiers)\n"
        "🏆 <b>/top5</b> — Top 5 strategies with full details\n"
        "⚖️ <b>/average</b> — AVERAGE tier strategies\n"
        "🔍 <b>/strategy</b> &lt;name&gt; — Search strategy by name\n"
        "💵 <b>/pnl</b> — Today's P&amp;L and open positions\n"
        "📊 <b>/categories</b> — Strategy risk categories (High vs Safe)\n"
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
# /winners — Quick Summary of ALL strategies (no scripts)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['winners'])
def cmd_winners(message):
    try:
        import pandas as pd
        report = PROJECT_ROOT / "storage/reports/tournament_winners.csv"
        df = pd.read_csv(report)

        # Count by tier
        alpha_pp = df[df['Tier'].str.contains('ALPHA\\+\\+', na=False)]
        alpha = df[df['Tier'].str.contains('ALPHA', na=False) & ~df['Tier'].str.contains('ALPHA\\+\\+', na=False)]
        average = df[df['Tier'].str.contains('AVERAGE', na=False)]
        reject = df[df['Tier'].str.contains('REJECT', na=False)]

        msg = "📊 <b>TOURNAMENT LEADERBOARD</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"🚀 <b>ALPHA++:</b> {len(alpha_pp)} strategies\n"
        msg += f"🎯 <b>ALPHA:</b> {len(alpha)} strategies\n"
        msg += f"⚖️ <b>AVERAGE:</b> {len(average)} strategies\n"
        msg += f"💀 <b>REJECT:</b> {len(reject)} strategies\n"
        msg += f"📈 <b>Total:</b> {len(df)} strategies\n\n"

        # Top 10 summary
        msg += "<b>TOP 10 STRATEGIES:</b>\n"
        for i, (_, r) in enumerate(df.head(10).iterrows()):
            tier_emoji = "🚀" if "ALPHA++" in str(r.get('Tier','')) else "🎯"
            msg += f"{tier_emoji} #{i+1} {r['Symbol']} | {str(r['Strategy'])[:30]} | ROI: {r['Daily_ROI_%']:.2f}%\n"

        msg += "\n<i>Use /alpha for full scripts | /top5 for details | /average for AVERAGE tier</i>"
        bot.reply_to(message, msg, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /top5 — Top 5 with full details (no scripts)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['top5'])
def cmd_top5(message):
    try:
        import pandas as pd
        report = PROJECT_ROOT / "storage/reports/tournament_winners.csv"
        df = pd.read_csv(report)

        msg = "🏆 <b>TOP 5 STRATEGIES</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"

        for i, (_, r) in enumerate(df.head(5).iterrows()):
            tier = str(r.get('Tier', ''))
            msg += f"<b>#{i+1} {r['Strategy']}</b>\n"
            msg += f"  📊 Symbol: {r['Symbol']}\n"
            msg += f"  📈 Daily ROI: {r['Daily_ROI_%']:.3f}%\n"
            _gdd = r.get('Gross_DD_%', 0)
            _gdd_cap = int(float(r.get('GDD_Capital_Left', 0))) or int(round(100000 * (1 + float(_gdd) / 100)))
            _ndd = r.get('Net_DD_%', 0)
            _ndd_cap = int(float(r.get('NDD_Capital_Left', 0))) or int(round(100000 * (1 + float(_ndd) / 100)))
            msg += f"  📉 Gross DD: {_gdd:.2f}%\n"
            msg += f"     📅 {r.get('GDD_Date', 'N/A')} | 💰 ${_gdd_cap:,} / $100K left\n"
            msg += f"  📉 Net DD: {_ndd:.2f}%\n"
            msg += f"     📅 {r.get('NDD_Date', 'N/A')} | 💰 ${_ndd_cap:,} / $100K left\n"
            msg += f"  🎯 Win Rate: {r.get('Win_Rate_%', 0):.1f}%\n"
            msg += f"  📐 Sharpe: {r.get('Sharpe_Ratio', 0):.2f}\n"
            msg += f"  🔄 Trades: {int(r.get('Total_Trades', 0))}\n"
            msg += f"  🏷️ Tier: {tier}\n"
            msg += f"  ⚙️ Params: Len={int(r.get('Optimal_Len', 0))}, Mult={r.get('Optimal_Mult', 0):.2f}\n\n"

        msg += "<i>Use /alpha for full Pine scripts</i>"
        bot.reply_to(message, msg, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /average — AVERAGE tier strategies with scripts
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['average'])
def cmd_average(message):
    try:
        import pandas as pd
        report = PROJECT_ROOT / "storage/reports/tournament_winners.csv"
        df = pd.read_csv(report)
        avg = df[df['Tier'].str.contains('AVERAGE', na=False)].head(10)

        if avg.empty:
            bot.reply_to(message, "No AVERAGE strategies found.")
            return

        msg = "⚖️ <b>AVERAGE TIER STRATEGIES (Top 10)</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"

        for i, (_, r) in enumerate(avg.iterrows()):
            msg += f"#{i+1} {r['Symbol']} | {str(r['Strategy'])[:35]}\n"
            msg += f"  ROI: {r['Daily_ROI_%']:.3f}% | WR: {r.get('Win_Rate_%', 0):.1f}% | DD: {r.get('Gross_DD_%', 0):.1f}%\n\n"

        msg += f"<i>Total AVERAGE: {len(df[df['Tier'].str.contains('AVERAGE', na=False)])} strategies</i>\n"
        msg += "<i>Use /average-scripts to get Pine scripts for these</i>"
        bot.reply_to(message, msg, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['average_scripts'])
def cmd_average_scripts(message):
    bot.reply_to(message, "⚖️ <b>Deploying AVERAGE tier scripts...</b>\nTop 15 incoming.", parse_mode='HTML')
    subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tradingview_webhook_bot/core/script_vault.py"), "--average"],
        cwd=str(PROJECT_ROOT)
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /strategy <name> — Search specific strategy
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['strategy'])
def cmd_strategy_search(message):
    try:
        import pandas as pd
        query = message.text.replace('/strategy', '').strip().lower()
        if not query:
            bot.reply_to(message, "Usage: /strategy <name>\nExample: /strategy ema cloud")
            return

        report = PROJECT_ROOT / "storage/reports/tournament_winners.csv"
        df = pd.read_csv(report)
        matches = df[df['Strategy'].str.lower().str.contains(query, na=False)]

        if matches.empty:
            bot.reply_to(message, f"❌ No strategy found matching '{query}'")
            return

        msg = f"🔍 <b>Search: '{query}'</b> — {len(matches)} results\n\n"
        for i, (_, r) in enumerate(matches.head(10).iterrows()):
            tier = str(r.get('Tier', ''))
            tier_emoji = "🚀" if "ALPHA++" in tier else "🎯" if "ALPHA" in tier else "⚖️" if "AVERAGE" in tier else "💀"
            msg += f"{tier_emoji} {r['Symbol']} | {r['Strategy']}\n"
            msg += f"  ROI: {r['Daily_ROI_%']:.3f}% | WR: {r.get('Win_Rate_%',0):.1f}% | Sharpe: {r.get('Sharpe_Ratio',0):.2f} | {tier}\n\n"

        bot.reply_to(message, msg, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        "💵 <b>/pnl</b> — Today's P&amp;L and open positions\n"
        "📊 <b>/categories</b> — Strategy risk categories (High vs Safe)\n"
@bot.message_handler(commands=['pnl'])
def cmd_pnl(message):
    try:
        import json
        ledger_path = PROJECT_ROOT / "tradingview_webhook_bot/storage/ledger_state.json"
        with open(ledger_path) as f:
            state = json.load(f)

        daily_pnl = state.get('daily_pnl', 0)
        positions = state.get('positions', {})
        open_pos = {k: v for k, v in positions.items() if v.get('quantity', 0) != 0}

        msg = "💵 <b>TODAY'S PERFORMANCE</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"
        msg += f"📈 <b>Daily PnL:</b> <code>${daily_pnl:.2f}</code>\n"
        msg += f"📊 <b>Open Positions:</b> {len(open_pos)}\n\n"

        if open_pos:
            msg += "<b>Open Positions:</b>\n"
            for key, pos in open_pos.items():
                qty = pos.get('quantity', 0)
                avg = pos.get('avg_price', 0)
                side = "LONG" if qty > 0 else "SHORT"
                msg += f"  {'🟢' if qty > 0 else '🔴'} {key} | {side} {abs(qty):.4f} @ ${avg:.2f}\n"

        bot.reply_to(message, msg, parse_mode='HTML')
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=["categories"])
# /categories — Strategy risk categories
def cmd_categories(message):
    try:
        import pandas as pd
        df = pd.read_csv('storage/reports/tournament_winners.csv')
        cat1 = df[(df['Daily_ROI_%'] >= 1.5) & (df['Net_DD_%'].abs() >= 75)].sort_values('Daily_ROI_%', ascending=False)
        cat2 = df[df['Daily_ROI_%'] > 0].sort_values('Net_DD_%', ascending=False).head(10)
        lines = ["STRATEGY CATEGORIES", "=" * 20, ""]
        lines.append("CAT 1: HIGH RETURN + HIGH RISK")
        lines.append("(ROI >1.5%/day, DD >75%)")
        lines.append("")
        for _, r in cat1.head(5).iterrows():
            nd = abs(r['Net_DD_%'])
            cap = int(10000 * (1 - nd/100))
            lines.append("  %s | %s" % (r['Symbol'], str(r['Strategy'])[:28]))
            lines.append("  ROI: %.2f%% | DD: %.1f%% | Worst: $%d" % (r['Daily_ROI_%'], nd, cap))
            lines.append("")
        lines.append("CAT 2: SAFE + STEADY")
        lines.append("(Lowest DD, capital >$8,000)")
        lines.append("")
        for _, r in cat2.head(5).iterrows():
            nd = abs(r['Net_DD_%'])
            cap = int(10000 * (1 - nd/100))
            lines.append("  %s | %s" % (r['Symbol'], str(r['Strategy'])[:28]))
            lines.append("  ROI: %.2f%% | DD: %.1f%% | Worst: $%d" % (r['Daily_ROI_%'], nd, cap))
            lines.append("")
        lines.append("Cat 1: %d | Cat 2: %d strategies" % (len(cat1), len(cat2)))
        bot.send_message(message.chat.id, chr(10).join(lines))
    except Exception as e:
        bot.send_message(message.chat.id, "Error: %s" % str(e))

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
            strat = str(row['Strategy'])[:30]
            roi = round(row['Daily_ROI_%'], 3)
            gross_dd = round(row.get('Gross_DD_%', row.get('Max_DD_%', 0)), 2)
            net_dd = round(row.get('Net_DD_%', gross_dd), 2)
            gdd_date = row.get('GDD_Date', 'N/A')
            gdd_capital = int(float(row.get('GDD_Capital_Left', 0))) or int(round(100000 * (1 + gross_dd / 100)))
            ndd_date = row.get('NDD_Date', 'N/A')
            ndd_capital = int(float(row.get('NDD_Capital_Left', 0))) or int(round(100000 * (1 + net_dd / 100)))
            tier = row.get('Tier', 'N/A')

            win_rate = round(row.get('Win_Rate_%', 0), 1)
            sharpe = round(row.get('Sharpe_Ratio', 0), 2)

            lines.append(
                f"\n<b>#{i+1}</b> {tier}\n"
                f"   {symbol} | {strat}\n"
                f"   📈 ROI: <code>{roi}%</code>/day\n"
                f"   📉 Gross DD: <code>{gross_dd}%</code>\n"
                f"      📅 {gdd_date} | 💰 ${gdd_capital:,} / $100K left\n"
                f"   📉 Net DD: <code>{net_dd}%</code>\n"
                f"      📅 {ndd_date} | 💰 ${ndd_capital:,} / $100K left\n"
                f"   🎯 Win: <code>{win_rate}%</code> | Sharpe: <code>{sharpe}</code>"
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
    print('Telegram Listener starting...')
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

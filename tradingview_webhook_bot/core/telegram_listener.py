import os, sys, time, subprocess, sqlite3
import pandas as pd
import json
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
STOP_FLAG_FILE = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/STOP_DISPATCH")
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "config", "approved_strategies.json")

# State tracker for /new_strat_mani conversations
_pending_manifest_adds = {}

bot = telebot.TeleBot(TOKEN)

# ── Active subprocess tracker ─────────────────────────────────────────────────
# Stores running Popen objects keyed by command name (e.g. "alpha", "average")
_active_processes: dict = {}

def _kill_active(name: str) -> bool:
    """Kill a tracked subprocess + any OS-level script_vault.py process.
    Returns True if something was killed.
    Works even if telegram_listener was restarted (proc ref lost)."""
    killed = False
    proc = _active_processes.pop(name, None)
    if proc and proc.poll() is None:
        try:
            proc.kill()
            killed = True
        except Exception:
            pass
    # OS-level fallback: pkill finds the process even without a stored reference
    try:
        result = subprocess.run(
            ["pkill", "-f", "script_vault.py"],
            capture_output=True, timeout=3
        )
        if result.returncode == 0:
            killed = True
    except Exception:
        pass
    return killed

def _stop_all() -> list:
    """Kill all active subprocesses and set the stop flag. Returns list of stopped names."""
    stopped = []
    # Create stop flag file so script_vault exits cleanly between messages
    try:
        with open(STOP_FLAG_FILE, "w") as _f:
            _f.write("stop")
    except Exception:
        pass
    for name in list(_active_processes.keys()):
        if _kill_active(name):
            stopped.append(name)
    return stopped

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
        "⚖️ <b>/average_scripts</b> — Deploy AVERAGE tier Pine scripts\n"
        "🔍 <b>/strategy</b> &lt;name&gt; — Search strategy by name\n"
        "💵 <b>/pnl</b> — Today's P&amp;L and open positions\n"
        "📊 <b>/categories</b> — Strategy risk categories (High vs Safe)\n"
        "📊 <b>/status</b> — Live system health\n"
        "🔍 <b>/audit</b> — Tournament Leaderboard Top 10\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>MANIFEST COMMANDS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 <b>/new_strat_mani</b> — Add strategy to approval manifest\n"
        "📋 <b>/list_manifest</b> — Show all approved strategies\n"
        "🗑️ <b>/remove_strat_mani</b> &lt;name&gt; — Remove strategy from manifest\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛑 <b>STOP COMMANDS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🛑 <b>/stop</b> — Cancel ALL running deployments immediately\n"
        "🛑 <b>/stop_alpha</b> — Stop only /alpha deployment\n"
        "🛑 <b>/stop_average_scripts</b> — Stop only /average_scripts deployment\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💹 <b>/buy SYMBOL</b> — Manual BUY. Example: <code>/buy SOLUSDT</code>\n"
        "💹 <b>/sell SYMBOL</b> — Manual SELL. Example: <code>/sell ETHUSDT</code>\n"
        "⚡ <b>/override SYMBOL</b> — Force BUY (bypasses tier check)\n\n"

        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Engine v11.0:</b>\n"
        "• Pine scripts = only verified ALPHA (same condition as live trades)\n"
        "• REVERSE_ALPHA excluded from Pine (signal flip handled server-side)\n"
        "• ADX &gt; 20 + ATR Vol Filter + 2% Trail Stop + Daily Circuit Breaker\n"
        "• /stop works mid-deployment — sends confirmation when halted"
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
    # Kill any existing alpha deployment first
    if _kill_active("alpha"):
        bot.reply_to(message, "⚠️ Previous /alpha deployment was running — killed it. Starting fresh.", parse_mode='HTML')
    bot.reply_to(message, "🚀 <b>Deploying Alpha Strategies...</b>\nPine Scripts incoming.\n\n<i>Send /stop or /stop_alpha to cancel.</i>", parse_mode='HTML')
    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tradingview_webhook_bot/core/script_vault.py")],
        cwd=str(PROJECT_ROOT)
    )
    _active_processes["alpha"] = proc

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
    if _kill_active("average"):
        bot.reply_to(message, "⚠️ Previous /average_scripts deployment was running — killed it. Starting fresh.", parse_mode='HTML')
    bot.reply_to(message, "⚖️ <b>Deploying AVERAGE tier scripts...</b>\nTop 15 incoming.\n\n<i>Send /stop or /stop_average_scripts to cancel.</i>", parse_mode='HTML')
    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "tradingview_webhook_bot/core/script_vault.py"), "--average"],
        cwd=str(PROJECT_ROOT)
    )
    _active_processes["average"] = proc

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /stop — Cancel any running deployment
# /stop_alpha, /stop_average_scripts — Specific stop commands
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['stop', 'stop_alpha', 'stop_average_scripts', 'stop_buy', 'stop_sell'])
def cmd_stop(message):
    cmd = message.text.split()[0].replace('/', '').lower()

    if cmd == 'stop':
        # Stop EVERYTHING currently running
        stopped = _stop_all()
        if stopped:
            bot.reply_to(message, f"🛑 <b>STOPPED</b>\n\nKilled: {', '.join(stopped)}\nStop flag set — script_vault will halt after current message.", parse_mode='HTML')
        else:
            # Still set stop flag in case a subprocess is mid-sleep
            try:
                with open(STOP_FLAG_FILE, "w") as _f:
                    _f.write("stop")
            except Exception:
                pass
            bot.reply_to(message, "🛑 <b>Stop flag set.</b>\nNo active deployment found, but flag is active for 60s.", parse_mode='HTML')

    elif cmd == 'stop_alpha':
        killed = _kill_active("alpha")
        try:
            with open(STOP_FLAG_FILE, "w") as _f:
                _f.write("stop")
        except Exception:
            pass
        bot.reply_to(message, f"🛑 <b>/alpha deployment {'stopped ✅' if killed else 'was not running.'}</b>", parse_mode='HTML')

    elif cmd == 'stop_average_scripts':
        killed = _kill_active("average")
        try:
            with open(STOP_FLAG_FILE, "w") as _f:
                _f.write("stop")
        except Exception:
            pass
        bot.reply_to(message, f"🛑 <b>/average_scripts deployment {'stopped ✅' if killed else 'was not running.'}</b>", parse_mode='HTML')

    else:
        # stop_buy / stop_sell — nothing async to kill, just ack
        bot.reply_to(message, f"ℹ️ <code>/{cmd}</code>: Manual trade commands are instant — nothing to stop.", parse_mode='HTML')

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
# /new_strat_mani — Add strategy to approval manifest
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['new_strat_mani'])
def cmd_new_strat_manifest(message):
    format_msg = (
        "📋 <b>Add Strategy to Approval Manifest</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Send the strategy details in this format:\n\n"
        "<code>"
        "strategy: CCI Trend\n"
        "exchange: binance\n"
        "symbols: ETHUSDT, BTCUSDT\n"
        "timeframes: 240\n"
        "operator: harsh\n"
        "label: ALPHA\n"
        "notes: ROI=5.91%, PF=1.14, DD=-2.82%"
        "</code>\n\n"
        "📌 <b>Rules:</b>\n"
        "• <b>strategy</b> — exact name as TradingView sends\n"
        "• <b>symbols</b> — comma separated, or <code>*</code> for all\n"
        "• <b>timeframes</b> — comma separated, or <code>*</code> for all\n"
        "• <b>exchange</b> — binance / lighter / hyperliquid\n"
        "• <b>label</b> — ALPHA / PREMIUM / APPROVED\n\n"
        "💡 Reply to THIS message with the details."
    )
    sent = bot.reply_to(message, format_msg, parse_mode='HTML')
    _pending_manifest_adds[message.chat.id] = sent.message_id


@bot.message_handler(func=lambda m: m.chat.id in _pending_manifest_adds and m.reply_to_message and m.reply_to_message.message_id == _pending_manifest_adds.get(m.chat.id))
def handle_manifest_reply(message):
    try:
        text = message.text.strip()
        lines = text.split("\n")
        data = {}
        for line in lines:
            if ":" in line:
                key, _, val = line.partition(":")
                data[key.strip().lower()] = val.strip()

        # Validate required fields
        strategy = data.get("strategy", "").strip()
        if not strategy:
            bot.reply_to(message, "❌ <b>Missing 'strategy' field.</b> Please try again.", parse_mode='HTML')
            return

        exchange = data.get("exchange", "binance").strip().lower()
        symbols_raw = data.get("symbols", "*").strip()
        symbols = [s.strip().upper() for s in symbols_raw.split(",") if s.strip()] or ["*"]
        timeframes_raw = data.get("timeframes", "*").strip()
        timeframes = [t.strip() for t in timeframes_raw.split(",") if t.strip()] or ["*"]
        operator = data.get("operator", "telegram").strip()
        label = data.get("label", "APPROVED").strip()
        notes = data.get("notes", "").strip()

        from datetime import datetime, timezone

        approval = {
            "strategy": strategy,
            "exchange": exchange,
            "symbols": symbols,
            "timeframes": timeframes,
            "operator": operator,
            "approved_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "backtest_hash": "telegram_approved",
            "label": label,
            "notes": notes,
        }

        # Load manifest
        manifest_path = MANIFEST_PATH
        if os.path.exists(manifest_path):
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
        else:
            manifest = {"version": 1, "approvals": []}

        manifest.setdefault("approvals", [])

        # Check for duplicate
        strat_lower = strategy.lower()
        for existing in manifest["approvals"]:
            if existing.get("strategy", "").lower() == strat_lower and existing.get("exchange", "").lower() == exchange:
                existing_syms = [s.upper() for s in existing.get("symbols", [])]
                if existing_syms == symbols:
                    bot.reply_to(message, f"⚠️ <b>{strategy}</b> already exists in manifest for {exchange} / {', '.join(symbols)}. Use /remove_strat_mani first to update.", parse_mode='HTML')
                    _pending_manifest_adds.pop(message.chat.id, None)
                    return

        manifest["approvals"].append(approval)
        manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

        total = len(manifest["approvals"])
        confirm = (
            f"✅ <b>Strategy Approved!</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"📋 <b>Strategy:</b> <code>{strategy}</code>\n"
            f"🏦 <b>Exchange:</b> <code>{exchange}</code>\n"
            f"💎 <b>Symbols:</b> <code>{', '.join(symbols)}</code>\n"
            f"⏰ <b>Timeframes:</b> <code>{', '.join(timeframes)}</code>\n"
            f"👤 <b>Operator:</b> <code>{operator}</code>\n"
            f"🏷️ <b>Label:</b> <code>{label}</code>\n"
            f"📝 <b>Notes:</b> {notes or 'N/A'}\n\n"
            f"📊 <b>Total approved strategies:</b> {total}\n\n"
            f"⚡ <i>Live immediately — no restart needed.</i>"
        )
        bot.reply_to(message, confirm, parse_mode='HTML')
        _pending_manifest_adds.pop(message.chat.id, None)

    except Exception as e:
        bot.reply_to(message, f"❌ <b>Error:</b> {e}", parse_mode='HTML')
        _pending_manifest_adds.pop(message.chat.id, None)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /list_manifest — Show all approved strategies
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['list_manifest'])
def cmd_list_manifest(message):
    try:
        if not os.path.exists(MANIFEST_PATH):
            bot.reply_to(message, "📋 Manifest not found. No strategies approved yet.", parse_mode='HTML')
            return

        with open(MANIFEST_PATH, 'r') as f:
            manifest = json.load(f)

        approvals = manifest.get("approvals", [])
        if not approvals:
            bot.reply_to(message, "📋 <b>Manifest is empty.</b> No approved strategies.\n\nUse /new_strat_mani to add one.", parse_mode='HTML')
            return

        msg = f"📋 <b>Approved Strategies ({len(approvals)})</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━\n\n"

        for i, a in enumerate(approvals):
            symbols = ', '.join(a.get('symbols', ['*']))
            tfs = ', '.join(a.get('timeframes', ['*']))
            msg += (
                f"<b>#{i+1} {a.get('strategy', 'N/A')}</b>\n"
                f"  🏦 {a.get('exchange', 'N/A')} | 💎 {symbols} | ⏰ {tfs}\n"
                f"  🏷️ {a.get('label', 'N/A')} | 👤 {a.get('operator', 'N/A')}\n"
                f"  📅 {a.get('approved_at', 'N/A')}\n\n"
            )

        msg += f"<i>Updated: {manifest.get('updated_at', 'N/A')}</i>"
        bot.reply_to(message, msg, parse_mode='HTML')

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", parse_mode='HTML')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# /remove_strat_mani — Remove strategy from manifest
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['remove_strat_mani'])
def cmd_remove_manifest(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "❌ <b>Usage:</b> <code>/remove_strat_mani Strategy Name</code>\n\nExample: <code>/remove_strat_mani CCI Trend</code>\n\nUse /list_manifest to see current strategies.", parse_mode='HTML')
        return

    strategy_name = args[1].strip()
    try:
        if not os.path.exists(MANIFEST_PATH):
            bot.reply_to(message, "📋 Manifest not found.", parse_mode='HTML')
            return

        with open(MANIFEST_PATH, 'r') as f:
            manifest = json.load(f)

        approvals = manifest.get("approvals", [])
        original_count = len(approvals)
        strat_lower = strategy_name.lower()

        manifest["approvals"] = [a for a in approvals if a.get("strategy", "").lower() != strat_lower]
        removed_count = original_count - len(manifest["approvals"])

        if removed_count == 0:
            bot.reply_to(message, f"⚠️ Strategy '<b>{strategy_name}</b>' not found in manifest.\n\nUse /list_manifest to see current strategies.", parse_mode='HTML')
            return

        from datetime import datetime, timezone
        manifest["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

        with open(MANIFEST_PATH, 'w') as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")

        remaining = len(manifest["approvals"])
        bot.reply_to(message, f"🗑️ <b>Removed:</b> <code>{strategy_name}</code>\n\n✅ {removed_count} entry removed. {remaining} strategies remaining.\n\n⚡ <i>Live immediately — no restart needed.</i>", parse_mode='HTML')

    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}", parse_mode='HTML')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if __name__ == "__main__":
    print('Telegram Listener starting...')
    bot.infinity_polling(timeout=60, long_polling_timeout=60)

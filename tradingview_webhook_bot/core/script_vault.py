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
    telegram.send(severity=AlertSeverity.INFO, title="Alpha Engine v10.0 [GOD MODE + DD SHIELD]",
                  message=f"🛡️ <b>PERMANENT ERROR BYPASS ACTIVE</b>\nDeploying {len(targets)} scripts with Zero-Margin logic.\n🛡️ <b>DD Reduction:</b> ADX &gt; 25 Filter + 4% Trailing Stop Active.")
    time.sleep(3)

    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        mult = winner.get('Optimal_Mult', 3.0)
        length = int(winner.get('Optimal_Len', 14))
        roi = round(float(winner.get('Daily_ROI_%', 0.0)), 3)
        gross_dd = round(float(winner.get('Gross_DD_%', winner.get('Max_DD_%', 0.0))), 2)
        net_dd = round(float(winner.get('Net_DD_%', gross_dd)), 2)
        win_rate = round(float(winner.get('Win_Rate_%', 0.0)), 1)
        sharpe = round(float(winner.get('Sharpe_Ratio', 0.0)), 2)
        total_trades = int(winner.get('Total_Trades', 0))

        # 🎯 Logic Injection
        if any(k in strat.upper() for k in ["SMC", "LIQUIDITY", "FLOW", "BARUPDN"]):
             core_logic = f"lookback = {length}\nlong = close > close[lookback]\nshort = close < close[lookback]"
        elif any(k in strat.upper() for k in ["SUPERTREND"]):
             core_logic = f"[st, dir] = ta.supertrend({mult}, {length})\nlong = ta.crossover(close, st)\nshort = ta.crossunder(close, st)"
        else:
             core_logic = f"basis = ta.sma(close, {length})\ndev = {mult} * ta.stdev(close, {length})\nlong = close < basis - dev\nshort = close > basis + dev"

        # 🔥 THE "GOD MODE" TEMPLATE (No Equity Dependency)
        # 🛡️ UPDATE 1: ADX > 25 Filter + 4% Trailing Stop for DD Reduction
        pine_code = f"""//@version=5
strategy("AI {symbol} Rank{i+1}", overlay=true, initial_capital=100000000, currency=currency.USD, margin_long=0, margin_short=0)

// --- Strategy Logic ---
{core_logic}

// --- 🛡️ Institutional DD Reduction: ADX Filter ---
// Choppy market filter: Only trade when ADX > 25 (strong trend confirmed)
[diPlus, diMinus, adxValue] = ta.dmi(14, 14)
adx_filter = adxValue > 25

// --- 🛡️ Zero-Error Execution Engine ---
// Hum fixed qty use kar rahe hain taaki TV engine crash na ho
fixed_qty = 10
start_time = timestamp(2024, 01, 01, 00, 00)

// --- 🔒 4% Trailing Stop Loss (Profit Locking) ---
trail_pct = 4.0

if (time >= start_time)
    if long and adx_filter
        strategy.entry("Long", strategy.long, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
        strategy.exit("Trail Long", "Long", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
    if short and adx_filter
        strategy.entry("Short", strategy.short, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
        strategy.exit("Trail Short", "Short", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
"""
        safe_code = html.escape(pine_code)
        
        # Telegram Dispatch
        msg = (f"🏆 <b>RANK #{i+1} WINNER</b> 🏆\n"
               f"📊 Symbol: {symbol}\n"
               f"📈 Daily ROI: {roi}%\n"
               f"📉 Gross DD: {gross_dd}% (Compounding)\n"
               f"📉 Net DD: {net_dd}% (Fixed Size)\n"
               f"🎯 Win Rate: {win_rate}% | Sharpe: {sharpe}\n"
               f"🔄 Total Trades: {total_trades}\n"
               f"🛡️ ADX &gt; 25 Filter: ON | Trailing Stop: 4%")

        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Stats", message=msg)
        time.sleep(3)  # 3s between stats and code to avoid 429
        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} [SECURE] Code", message=f"<code>{safe_code}</code>")

        print(f"Dispatched {symbol} Rank #{i+1} in God Mode.")
        time.sleep(4)  # 4s between strategies (Telegram allows ~20 msg/min to same chat)

if __name__ == "__main__":
    dispatch_top_strategies(force=True)

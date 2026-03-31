import os, sys, json, pandas as pd, html, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Path setup
FILE_PATH = Path(__file__).resolve()
PROJECT_ROOT = FILE_PATH.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Stop flag file — created by /stop command in telegram_listener
STOP_FLAG_FILE = os.path.join(PROJECT_ROOT, "tradingview_webhook_bot/storage/STOP_DISPATCH")

def _should_stop():
    """Returns True and cleans up flag if a stop was requested."""
    if os.path.exists(STOP_FLAG_FILE):
        try:
            os.remove(STOP_FLAG_FILE)
        except Exception:
            pass
        return True
    return False

def _interruptible_sleep(seconds):
    """Sleep in 0.5s chunks. Returns True immediately if stop flag appears.
    Does NOT consume the flag — caller should check _should_stop() after."""
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(min(0.5, end - time.time()))
        if os.path.exists(STOP_FLAG_FILE):
            return True
    return False

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
        # Match EXACTLY what the orchestrator allows:
        # - Tier contains "ALPHA" (same check as check_tournament_alpha line 489)
        # - Exclude REVERSE_ strategies (they don't have independent Pine scripts)
        # - Exclude BLOCKED
        # - Drop duplicates: keep best ROI per Symbol+Strategy pair
        _tier = df['Tier'].astype(str)
        targets = (
            df[
                _tier.str.contains('ALPHA', na=False) &
                ~_tier.str.contains('REVERSE', na=False) &
                ~_tier.str.contains('BLOCKED', na=False)
            ]
            .drop_duplicates(subset=['Symbol', 'Strategy'])
            .sort_values(by='Daily_ROI_%', ascending=False)
        )
    except Exception as e:
        print(f"❌ Error: {e}")
        return

    # Clear any leftover stop flag from previous run
    if os.path.exists(STOP_FLAG_FILE):
        os.remove(STOP_FLAG_FILE)

    # Header Message
    telegram.send(severity=AlertSeverity.INFO, title="Alpha Engine v11.0 [LOW DD MODE]",
                  message=f"🛡️ <b>DD SHIELD v2 ACTIVE</b>\nDeploying {len(targets)} scripts — 1x Leverage, NDD &lt; -50% target.\n🛡️ <b>Filters:</b> ADX &gt; 20 + ATR Vol Filter + 2% Trail Stop + Daily Circuit Breaker.\n\n<i>Send /stop to cancel at any time.</i>")
    time.sleep(3)

    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        mult = winner.get('Optimal_Mult', 3.0)
        length = int(winner.get('Optimal_Len', 14))
        roi = round(float(winner.get('Daily_ROI_%', 0.0)), 3)
        gross_dd = round(float(winner.get('Gross_DD_%', winner.get('Max_DD_%', 0.0))), 2)
        net_dd = round(float(winner.get('Net_DD_%', gross_dd)), 2)
        gdd_date = str(winner.get('GDD_Date', 'N/A'))
        gdd_capital = int(float(winner.get('GDD_Capital_Left', 0)))
        if gdd_capital == 0 and gross_dd != 0:
            gdd_capital = int(round(100000 * (1 + gross_dd / 100), 0))
        ndd_date = str(winner.get('NDD_Date', 'N/A'))
        ndd_capital = int(float(winner.get('NDD_Capital_Left', 0)))
        if ndd_capital == 0 and net_dd != 0:
            ndd_capital = int(round(100000 * (1 + net_dd / 100), 0))
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

        # Clean strategy name for JSON (remove special chars)
        strat_clean = strat.replace("'", "").replace('"', '').replace(" ", "_").replace("[", "").replace("]", "").replace("+", "").replace("—", "-")

        # Professional display name: "Squeeze Flow Expansion | ETHUSDT - Webhook"
        strat_display = strat.replace("'", "").replace('"', '').strip()
        pine_name = f"{strat_display} | {symbol} - Webhook"

        # 🔥 THE "GOD MODE" TEMPLATE (No Equity Dependency)
        # 🛡️ UPDATE 1: ADX > 25 Filter + 4% Trailing Stop for DD Reduction
        # 🌐 UPDATE 2: Auto Webhook JSON — No manual JSON needed in TradingView
        pine_code = f"""//@version=5
strategy("{pine_name}", overlay=true, initial_capital=100000000, currency=currency.USD, margin_long=0, margin_short=0)

// --- Webhook Configuration ---
grp_wh = "Webhook Settings"
enable_webhook = input.bool(true, "Enable Webhook Alerts", group=grp_wh)
webhook_secret = input.string("squeeze_tradingview_cluster_2026_secure", "Webhook Secret", group=grp_wh)

// --- Strategy Logic ---
{core_logic}

// --- Institutional DD Reduction: ADX Filter ---
// Moderate trend filter: Only trade when ADX > 20 (relaxed from 25)
[diPlus, diMinus, adxValue] = ta.dmi(14, 14)
adx_filter = adxValue > 20

// --- ATR Volatility Filter ---
// Skip abnormally volatile periods (ATR > 2x its 100-bar average)
atrVal = ta.atr(14)
atrMA = ta.sma(atrVal, 100)
vol_filter = atrVal < atrMA * 2

// --- Zero-Error Execution Engine ---
fixed_qty = 10
start_time = timestamp(2024, 01, 01, 00, 00)

// --- 2% Trailing Stop Loss (Tighter for DD Reduction) ---
trail_pct = 2.0

// --- Timeframe Detection ---
tf_str = timeframe.period == "1D" ? "1d" : timeframe.period == "240" ? "4h" : timeframe.period == "60" ? "1h" : timeframe.period == "30" ? "30m" : timeframe.period == "15" ? "15m" : timeframe.period == "5" ? "5m" : timeframe.period == "1" ? "1m" : timeframe.period

if (time >= start_time)
    if long and adx_filter and vol_filter
        strategy.entry("Long", strategy.long, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
        strategy.exit("Trail Long", "Long", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
        if enable_webhook
            alert('{{"secret":"' + webhook_secret + '","strategy":"{strat_clean}","side":"BUY","symbol":"' + syminfo.ticker + '","timeframe":"' + tf_str + '","price":' + str.tostring(close) + ',"quantity":0.003,"exchange":"binance","indicator":"{strat_clean}","ROI":"{roi}%"}}', alert.freq_once_per_bar_close)
    if short and adx_filter and vol_filter
        strategy.entry("Short", strategy.short, qty=fixed_qty, comment='{{"ROI": "{roi}%"}}')
        strategy.exit("Trail Short", "Short", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
        if enable_webhook
            alert('{{"secret":"' + webhook_secret + '","strategy":"{strat_clean}","side":"SELL","symbol":"' + syminfo.ticker + '","timeframe":"' + tf_str + '","price":' + str.tostring(close) + ',"quantity":0.003,"exchange":"binance","indicator":"{strat_clean}","ROI":"{roi}%"}}', alert.freq_once_per_bar_close)
"""
        safe_code = html.escape(pine_code)
        
        # Check for stop command between each strategy
        if _should_stop():
            telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                          message=f"🛑 <b>/stop received</b> — Deployment halted after {i} of {len(targets)} scripts.")
            print(f"[script_vault] Stop flag detected — exiting after {i} strategies.")
            return

        # Telegram Dispatch
        tier_display = str(winner.get('Tier', 'ALPHA'))
        tier_emoji = "🚀" if "ALPHA++" in tier_display else "🎯" if "ALPHA" in tier_display else "⚖️"
        msg = (f"🏆 <b>RANK #{i+1} WINNER</b> 🏆\n"
               f"{tier_emoji} <b>Tier: {tier_display}</b>\n"
               f"📊 Symbol: {symbol}\n"
               f"📈 Daily ROI: {roi}%\n"
               f"📉 Gross DD: {gross_dd}% (Compounding)\n"
               f"   📅 {gdd_date} | 💰 ${gdd_capital:,} / $100K left\n"
               f"📉 Net DD: {net_dd}% (Fixed Size)\n"
               f"   📅 {ndd_date} | 💰 ${ndd_capital:,} / $100K left\n"
               f"🎯 Win Rate: {win_rate}% | Sharpe: {sharpe}\n"
               f"🔄 Total Trades: {total_trades}\n"
               f"⚙️ Params: Len={length}, Mult={mult}\n"
               f"🛡️ ADX &gt; 20 + ATR Vol Filter: ON | Trailing Stop: 2%")

        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} Stats", message=msg)
        if _interruptible_sleep(3):
            if _should_stop():
                telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                              message=f"🛑 <b>/stop received</b> — Deployment halted after {i} of {len(targets)} scripts.")
            return
        telegram.send(severity=AlertSeverity.INFO, title=f"Rank #{i+1} [SECURE] Code", message=f"<code>{safe_code}</code>")

        print(f"Dispatched {symbol} Rank #{i+1} in God Mode.")
        if _interruptible_sleep(4):
            if _should_stop():
                telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                              message=f"🛑 <b>/stop received</b> — Deployment halted after {i+1} of {len(targets)} scripts.")
            return

def dispatch_average_strategies():
    """Send AVERAGE tier strategies with Pine scripts."""
    telegram = TelegramAlert()
    report_path = os.path.join(PROJECT_ROOT, "storage/reports/tournament_winners.csv")

    try:
        df = pd.read_csv(report_path)
        targets = df[df['Tier'].str.contains('AVERAGE', na=False)].sort_values(by='Daily_ROI_%', ascending=False).head(15)
    except Exception as e:
        print(f"Error: {e}")
        return

    if os.path.exists(STOP_FLAG_FILE):
        os.remove(STOP_FLAG_FILE)

    telegram.send(severity=AlertSeverity.INFO, title="Average Tier Deployment",
                  message=f"⚖️ <b>Deploying {len(targets)} AVERAGE strategies</b>\nThese require manual approval before live trading.\n\n<i>Send /stop to cancel at any time.</i>")
    time.sleep(3)

    for i, (_, winner) in enumerate(targets.iterrows()):
        symbol = str(winner['Symbol']).upper()
        strat = str(winner['Strategy'])
        mult = winner.get('Optimal_Mult', 3.0)
        length = int(winner.get('Optimal_Len', 14))
        roi = round(float(winner.get('Daily_ROI_%', 0.0)), 3)
        gross_dd = round(float(winner.get('Gross_DD_%', winner.get('Max_DD_%', 0.0))), 2)
        net_dd = round(float(winner.get('Net_DD_%', gross_dd)), 2)
        gdd_date = str(winner.get('GDD_Date', 'N/A'))
        gdd_capital = int(float(winner.get('GDD_Capital_Left', 0)))
        if gdd_capital == 0 and gross_dd != 0:
            gdd_capital = int(round(100000 * (1 + gross_dd / 100), 0))
        ndd_date = str(winner.get('NDD_Date', 'N/A'))
        ndd_capital = int(float(winner.get('NDD_Capital_Left', 0)))
        if ndd_capital == 0 and net_dd != 0:
            ndd_capital = int(round(100000 * (1 + net_dd / 100), 0))
        win_rate = round(float(winner.get('Win_Rate_%', 0.0)), 1)
        sharpe = round(float(winner.get('Sharpe_Ratio', 0.0)), 2)
        total_trades = int(winner.get('Total_Trades', 0))

        if any(k in strat.upper() for k in ["SMC", "LIQUIDITY", "FLOW", "BARUPDN"]):
            core_logic = f"lookback = {length}\nlong = close > close[lookback]\nshort = close < close[lookback]"
        elif any(k in strat.upper() for k in ["SUPERTREND"]):
            core_logic = f"[st, dir] = ta.supertrend({mult}, {length})\nlong = ta.crossover(close, st)\nshort = ta.crossunder(close, st)"
        else:
            core_logic = f"basis = ta.sma(close, {length})\ndev = {mult} * ta.stdev(close, {length})\nlong = close < basis - dev\nshort = close > basis + dev"

        strat_clean = strat.replace("'", "").replace('"', '').replace(" ", "_").replace("[", "").replace("]", "").replace("+", "").replace("\u2014", "-")
        strat_display = strat.replace("'", "").replace('"', '').strip()
        pine_name = f"{strat_display} | {symbol} - Webhook"

        pine_code = f"""//@version=5
strategy("{pine_name}", overlay=true, initial_capital=100000000, currency=currency.USD, margin_long=0, margin_short=0)
grp_wh = "Webhook Settings"
enable_webhook = input.bool(true, "Enable Webhook Alerts", group=grp_wh)
webhook_secret = input.string("squeeze_tradingview_cluster_2026_secure", "Webhook Secret", group=grp_wh)
{core_logic}
[diPlus, diMinus, adxValue] = ta.dmi(14, 14)
adx_filter = adxValue > 20
atrVal = ta.atr(14)
atrMA = ta.sma(atrVal, 100)
vol_filter = atrVal < atrMA * 2
fixed_qty = 10
start_time = timestamp(2024, 01, 01, 00, 00)
trail_pct = 2.0
if (time >= start_time)
    if long and adx_filter and vol_filter
        strategy.entry("Long", strategy.long, qty=fixed_qty)
        strategy.exit("Trail Long", "Long", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
    if short and adx_filter and vol_filter
        strategy.entry("Short", strategy.short, qty=fixed_qty)
        strategy.exit("Trail Short", "Short", trail_points=close * trail_pct / 100 / syminfo.mintick, trail_offset=close * trail_pct / 100 / syminfo.mintick)
"""
        safe_code = html.escape(pine_code)
        msg = (f"⚖️ <b>AVERAGE #{i+1}</b>\n"
               f"📊 {symbol} | {strat_display[:40]}\n"
               f"📈 ROI: {roi}% | WR: {win_rate}% | Sharpe: {sharpe}\n"
               f"📉 Gross DD: {gross_dd}%\n"
               f"   📅 {gdd_date} | 💰 ${gdd_capital:,} / $100K left\n"
               f"📉 Net DD: {net_dd}%\n"
               f"   📅 {ndd_date} | 💰 ${ndd_capital:,} / $100K left\n"
               f"🔄 Trades: {total_trades}\n"
               f"⚙️ Params: Len={length}, Mult={mult}")

        if _should_stop():
            telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                          message=f"🛑 <b>/stop received</b> — Average deployment halted after {i} of {len(targets)} scripts.")
            return

        telegram.send(severity=AlertSeverity.INFO, title=f"Average #{i+1}", message=msg)
        if _interruptible_sleep(2):
            if _should_stop():
                telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                              message=f"🛑 <b>/stop received</b> — Average deployment halted after {i} of {len(targets)} scripts.")
            return
        telegram.send(severity=AlertSeverity.INFO, title=f"Average #{i+1} Code", message=f"<code>{safe_code}</code>")
        if _interruptible_sleep(3):
            if _should_stop():
                telegram.send(severity=AlertSeverity.INFO, title="Deployment Stopped",
                              message=f"🛑 <b>/stop received</b> — Average deployment halted after {i+1} of {len(targets)} scripts.")
            return

    print(f"Dispatched {len(targets)} AVERAGE strategies.")


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--average":
        dispatch_average_strategies()
    else:
        dispatch_top_strategies(force=True)

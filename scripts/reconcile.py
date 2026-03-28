#!/usr/bin/env python3
"""
AUTO-FIX Reconciler — closes orphan positions + cleans ledger automatically.
Run via cron every 15 min. No manual intervention needed.
"""
import sys, os, json, time, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
env_path = "/etc/tradingbot/env_vars"
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.exchange.binance_client import BinanceClient, fix_quantity
from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity

LEDGER_PATH = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/ledger_state.json"
# Max age for a position without SL/TP before auto-close (2 hours)
MAX_ORPHAN_AGE_SECONDS = 7200


def get_exchange_positions(client):
    """Get all open positions from Binance."""
    positions = {}
    try:
        raw = client.client.futures_position_information()
        for p in raw:
            amt = float(p.get('positionAmt', 0))
            if amt != 0:
                positions[p['symbol']] = {
                    'qty': amt,
                    'entry_price': float(p.get('entryPrice', 0)),
                    'unrealized_pnl': float(p.get('unRealizedProfit', 0)),
                    'update_time': float(p.get('updateTime', 0)) / 1000,
                }
    except Exception as e:
        logger.error(f"Failed to get exchange positions: {e}")
    return positions


def get_open_orders(client):
    """Get all open orders (SL/TP) per symbol."""
    orders_by_symbol = {}
    try:
        orders = client.client.futures_get_open_orders()
        for o in orders:
            sym = o['symbol']
            if sym not in orders_by_symbol:
                orders_by_symbol[sym] = []
            orders_by_symbol[sym].append(o)
    except Exception as e:
        logger.error(f"Failed to get open orders: {e}")
    return orders_by_symbol


def get_ledger_positions(ledger):
    """Get all non-zero positions from ledger."""
    positions = {}
    for key, pos in ledger.positions.items():
        if abs(pos.quantity) > 1e-10:
            positions[key] = pos.quantity
    return positions


def close_position(client, symbol, qty):
    """Close a position by market order."""
    side = "BUY" if qty < 0 else "SELL"
    abs_qty = fix_quantity(symbol, abs(qty))
    try:
        res = client.client.futures_create_order(
            symbol=symbol, side=side, type="MARKET", quantity=abs_qty,
            newClientOrderId=f"AUTOFIX_{symbol}_{int(time.time())}"
        )
        logger.info(f"Auto-closed {symbol}: {side} {abs_qty} (orderId: {res.get('orderId')})")
        return True
    except Exception as e:
        logger.error(f"Failed to close {symbol}: {e}")
        return False


def main():
    client = BinanceClient()
    ledger = PositionLedger(LEDGER_PATH)
    tg = TelegramAlert()

    exchange_pos = get_exchange_positions(client)
    open_orders = get_open_orders(client)
    ledger_pos = get_ledger_positions(ledger)

    fixes = []
    now = time.time()

    # CHECK 1: Exchange has position but NO SL/TP orders → orphan, auto-close
    for sym, pos in exchange_pos.items():
        has_sl_tp = sym in open_orders and len(open_orders[sym]) >= 1
        age = now - pos['update_time'] if pos['update_time'] > 0 else 0

        if not has_sl_tp and age > 900:  # 15 min without SL/TP = orphan  # No SL/TP and older than 5 min
            logger.warning(f"ORPHAN DETECTED: {sym} qty={pos['qty']} no SL/TP, age={age:.0f}s")
            if close_position(client, sym, pos['qty']):
                fixes.append(f"Auto-closed orphan {sym}: qty={pos['qty']}, PnL=${pos['unrealized_pnl']:.2f}")

    # CHECK 2: Ledger has ghost positions (ledger says position, exchange says flat)
    exchange_symbols = set(exchange_pos.keys())
    ghost_keys = []
    for key, qty in ledger_pos.items():
        # Extract symbol from key like "binance:SOLUSDT:strategy_name"
        parts = key.split(':')
        if len(parts) >= 2:
            sym = parts[1]
        else:
            sym = key
        # Clean symbol
        sym = sym.split('_')[0].replace('PREMIUM', '').replace('PERP', '')
        if 'USDT' not in sym:
            continue
        if sym not in exchange_symbols:
            ghost_keys.append(key)
            logger.warning(f"GHOST POSITION: ledger has {key}={qty} but exchange is flat")

    if ghost_keys:
        # Clean ghost positions from ledger
        for key in ghost_keys:
            if key in ledger.positions:
                ledger.positions[key].quantity = 0.0
                ledger.positions[key].avg_price = 0.0
        ledger._save_state()
        fixes.append(f"Cleaned {len(ghost_keys)} ghost positions from ledger")

    # CHECK 3: Exchange has position but ledger doesn't know → sync ledger
    for sym, pos in exchange_pos.items():
        found = False
        for key in ledger_pos:
            if sym in key:
                found = True
                break
        if not found:
            # Sync to ledger
            ledger.positions[sym] = type(list(ledger.positions.values())[0])(symbol=sym) if ledger.positions else None
            if ledger.positions.get(sym):
                ledger.positions[sym].quantity = pos['qty']
                ledger.positions[sym].avg_price = pos['entry_price']
            fixes.append(f"Synced {sym} to ledger: qty={pos['qty']}")

    if ghost_keys or fixes:
        ledger._save_state()

    # Report
    if fixes:
        msg = "🔧 AUTO-FIX RECONCILIATION\n━━━━━━━━━━━━━━━━━━\n\n"
        for f in fixes:
            msg += f"✅ {f}\n"
        msg += f"\n📊 Exchange: {len(exchange_pos)} positions\n"
        msg += f"📋 Ledger: {len(get_ledger_positions(ledger))} positions"
        logger.info(msg)
        try:
            tg.send(severity=AlertSeverity.INFO, title="Auto-Fix Reconciliation", message=msg)
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
    else:
        logger.info(f"All synced. Exchange: {len(exchange_pos)} positions, Ledger: {len(get_ledger_positions(ledger))} positions")


if __name__ == "__main__":
    main()

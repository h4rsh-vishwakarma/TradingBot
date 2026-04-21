#!/usr/bin/env python3
"""
Emergency Kill Switch — Close ALL positions and cancel ALL orders.
Usage:
  python3 scripts/kill_switch.py --emergency-stop   # Close everything
  python3 scripts/kill_switch.py --status            # Show current status
"""
import sys
import os
import json
import logging
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
env_path = "/etc/tradingbot/env_vars"
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

KILL_SWITCH_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "tradingview_webhook_bot", "storage", "KILL_SWITCH")
STATUS_FILE = os.path.join(os.path.dirname(KILL_SWITCH_FILE), "kill_switch_status.json")


def activate_kill_switch():
    with open(KILL_SWITCH_FILE, 'w') as f:
        f.write(f"ACTIVATED: {datetime.now().isoformat()}\n")
    print("Kill switch ACTIVATED — bot will not execute new trades")


def deactivate_kill_switch():
    if os.path.exists(KILL_SWITCH_FILE):
        os.remove(KILL_SWITCH_FILE)
        print("Kill switch DEACTIVATED — trading can resume")
    else:
        print("Kill switch was not active")


def emergency_stop():
    print("=" * 60)
    print("  EMERGENCY KILL SWITCH")
    print("  Closes ALL positions and cancels ALL orders.")
    print("=" * 60)

    confirm = input("\nType 'KILL' to confirm: ").strip()
    if confirm != "KILL":
        print("Aborted.")
        return

    closed = []
    from tradingview_webhook_bot.exchange.binance_client import BinanceClient
    client = BinanceClient()
    closed.extend(client.close_all_positions())

    lighter_key = os.getenv("LIGHTER_API_PRIVATE_KEY") or os.getenv("LIGHTER_PRIVATE_KEY")
    if lighter_key:
        try:
            from tradingview_webhook_bot.exchange.lighter_client import LighterClient
            lighter = LighterClient()
            closed.extend(lighter.close_all_positions())
            lighter.close()
        except Exception as exc:
            logger.error("Lighter emergency stop failed: %s", exc)
            closed.append({"exchange": "lighter", "status": "FAILED", "msg": str(exc)})

    print(f"\nClosed {len(closed)} positions:")
    for c in closed:
        side = c.get("side", c.get("action", "?"))
        qty = c.get("qty", c.get("quantity", ""))
        symbol = c.get("symbol", c.get("exchange", "?"))
        status = c.get("status", "SUCCESS")
        print(f"  {status}: {side} {qty} {symbol}")

    # Activate kill switch file
    activate_kill_switch()

    # Save status
    status = {
        "activated_at": datetime.now().isoformat(),
        "reason": "Manual emergency stop",
        "positions_closed": len(closed),
    }
    with open(STATUS_FILE, 'w') as f:
        json.dump(status, f, indent=2)

    # Notify via Telegram
    try:
        from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
        telegram = TelegramAlert()
        msg = f"🚨 KILL SWITCH (CLI)\nClosed {len(closed)} positions"
        telegram.send(severity=AlertSeverity.WARNING, title="KILL SWITCH", message=msg)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("EMERGENCY STOP COMPLETE")
    print("=" * 60)
    print("To resume: python3 scripts/kill_switch.py --deactivate")
    print("Then:      sudo systemctl restart trading_orchestrator trading_webhook")


def show_status():
    is_active = os.path.exists(KILL_SWITCH_FILE)
    print("=" * 60)
    print(f"Kill Switch: {'ACTIVE' if is_active else 'INACTIVE'}")
    if is_active and os.path.exists(STATUS_FILE):
        with open(STATUS_FILE) as f:
            status = json.load(f)
        print(f"Activated: {status['activated_at']}")
        print(f"Positions closed: {status['positions_closed']}")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Emergency Kill Switch')
    parser.add_argument('--emergency-stop', action='store_true', help='Close all positions')
    parser.add_argument('--activate', action='store_true', help='Activate kill switch (block trades)')
    parser.add_argument('--deactivate', action='store_true', help='Deactivate kill switch')
    parser.add_argument('--status', action='store_true', help='Show status')
    args = parser.parse_args()

    if args.emergency_stop:
        emergency_stop()
    elif args.activate:
        activate_kill_switch()
    elif args.deactivate:
        deactivate_kill_switch()
    elif args.status:
        show_status()
    else:
        parser.print_help()

#!/usr/bin/env python3
"""Reconcile ledger vs exchange positions. Run via cron every 15 min."""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from dotenv import load_dotenv
env_path = "/etc/tradingbot/env_vars"
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

from tradingview_webhook_bot.ledger.positions import PositionLedger
from tradingview_webhook_bot.exchange.binance_client import BinanceClient
from tradingview_webhook_bot.recon.reconciler import Reconciler

def main():
    ledger_path = "/home/ubuntu/tradingview_webhook_bot/tradingview_webhook_bot/storage/ledger_state.json"
    ledger = PositionLedger(ledger_path)
    client = BinanceClient()
    reconciler = Reconciler(ledger)

    exchange_data = client.get_audit_data()
    alerts = reconciler.reconcile_with_exchange(exchange_data)

    if alerts:
        print(f"Found {len(alerts)} drift(s):")
        for a in alerts:
            print(a)
        try:
            from tradingview_webhook_bot.alerts.telegram_alerts import TelegramAlert, AlertSeverity
            tg = TelegramAlert()
            for a in alerts:
                tg.send(severity=AlertSeverity.WARNING, title="Reconciliation", message=a)
        except Exception:
            pass
    else:
        print("All positions synced.")

if __name__ == "__main__":
    main()

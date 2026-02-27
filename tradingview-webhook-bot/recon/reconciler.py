"""
Reconciliation Engine (Day 4 Fully Updated)
Detects drift between the internal ledger and actual exchange balances.
Supports Pydantic model snapshots from the PositionLedger.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class Reconciler:
    def __init__(self, ledger, tolerance: float = 0.0001):
        """
        Args:
            ledger: The PositionLedger instance.
            tolerance: Allowed difference to account for rounding.
        """
        self.ledger = ledger
        self.tolerance = tolerance

    def reconcile_with_exchange(self, exchange_data: Dict[str, Any]) -> List[str]:
        """
        Primary entry point for the Automated Reconciliation Loop.
        Fixes the 'PositionSnapshot' object has no attribute 'get' error.
        """
        # Ledger positions ko extract karein (Pydantic objects ko floats mein convert karke)
        # PositionSnapshot attributes ko directly access karna zaroori hai
        ledger_positions = {
            sym: float(pos_obj.quantity) 
            for sym, pos_obj in getattr(self.ledger, 'positions', {}).items()
        }

        # Portfolio comparison logic run karein
        incidents = self.reconcile_portfolio(ledger_positions, exchange_data)
        
        # Alerts generate karein agar drift mile
        alert_messages = []
        for incident in incidents:
            alert_messages.append(self.format_incident(incident['symbol'], incident))
            
        return alert_messages

    def reconcile_portfolio(self, ledger_map: Dict[str, float], exchange_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Compares normalized ledger map against exchange data.
        """
        incidents = []
        # Exchange data format: { 'SYMBOL': {'quantity': float} }
        actual_map = {sym: float(data['quantity']) for sym, data in exchange_data.items()}

        # 1. Check Ledger entries against Exchange
        for symbol, expected_qty in ledger_map.items():
            actual_qty = actual_map.get(symbol, 0.0)
            report = self.detect_qty_drift(expected_qty, actual_qty)

            if not report["is_synced"]:
                report["symbol"] = symbol
                incidents.append(report)

            if symbol in actual_map:
                del actual_map[symbol]

        # 2. Check for Ghost Positions (Exchange only)
        for symbol, actual_qty in actual_map.items():
            if abs(actual_qty) > self.tolerance:
                report = self.detect_qty_drift(0.0, actual_qty)
                report["symbol"] = symbol
                incidents.append(report)

        return incidents

    def detect_qty_drift(self, ledger_qty: float, exchange_qty: float) -> Dict[str, Any]:
        """Calculates the absolute drift and determines sync status."""
        drift = abs(ledger_qty - exchange_qty)
        is_synced = drift <= self.tolerance

        return {
            "is_synced": is_synced,
            "drift": round(drift, 8),
            "ledger_qty": round(ledger_qty, 8),
            "exchange_qty": round(exchange_qty, 8),
            "severity": "CRITICAL" if not is_synced else "OK"
        }

    def format_incident(self, symbol: str, report: Dict[str, Any]) -> str:
        """Formats drift reports for Telegram/Alerting."""
        return (
            f"🚨 *RECONCILIATION ALARM: {symbol} DRIFT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Ledger:* `{report['ledger_qty']}`\n"
            f"📉 *Exchange:* `{report['exchange_qty']}`\n"
            f"❌ *Diff:* `{report['drift']}`\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

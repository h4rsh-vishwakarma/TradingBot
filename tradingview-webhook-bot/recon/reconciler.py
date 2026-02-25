"""
Reconciliation Engine
Detects drift between the internal ledger and actual exchange balances.
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class Reconciler:
    def __init__(self, tolerance: float = 0.0001):
        """
        Args:
            tolerance: The allowed difference between ledger and exchange
                       (to account for small rounding errors).
        """
        self.tolerance = tolerance

    def reconcile_portfolio(self, ledger_positions: Dict[str, float], exchange_positions: List[Dict]) -> List[Dict[str, Any]]:
        """
        Compares all ledger positions against actual exchange positions.
        Returns a list of incident reports for symbols that are out of sync.
        """
        incidents = []
        
        # 1. Normalize exchange data into a simple Dict { symbol: qty }
        # Binance returns long positions as positive and short as negative quantities
        actual_map = {
            pos['symbol']: float(pos.get('positionAmt', 0)) 
            for pos in exchange_positions 
            if float(pos.get('positionAmt', 0)) != 0
        }

        # 2. Check all symbols present in the Ledger
        for symbol, expected_qty in ledger_positions.items():
            actual_qty = actual_map.get(symbol, 0.0)
            report = self.detect_qty_drift(expected_qty, actual_qty)
            
            if not report["is_synced"]:
                report["symbol"] = symbol
                incidents.append(report)
            
            # Remove from map to see what's left
            if symbol in actual_map:
                del actual_map[symbol]

        # 3. Check for "Ghost Positions" (Exchange has them, Ledger doesn't)
        for symbol, actual_qty in actual_map.items():
            report = self.detect_qty_drift(0.0, actual_qty)
            if not report["is_synced"]:
                report["symbol"] = symbol
                incidents.append(report)

        return incidents

    def detect_qty_drift(self, ledger_qty: float, exchange_qty: float) -> Dict[str, Any]:
        """
        Compares ledger quantity vs exchange quantity.
        Returns a drift report.
        """
        drift = abs(ledger_qty - exchange_qty)
        is_synced = drift <= self.tolerance

        return {
            "is_synced": is_synced,
            "drift": drift,
            "ledger_qty": ledger_qty,
            "exchange_qty": exchange_qty,
            "severity": "CRITICAL" if not is_synced else "OK"
        }

    def format_incident(self, symbol: str, report: Dict[str, Any]) -> str:
        """Formats the drift report for alerts (Telegram/Logs)."""
        if report["is_synced"]:
            return f"✅ {symbol} is synced."

        return (
            f"🚨 RECONCILIATION ALARM: {symbol} DRIFT DETECTED!\n"
            f"----------------------------------\n"
            f"📈 Expected (Ledger): {report['ledger_qty']}\n"
            f"📉 Actual (Exchange): {report['exchange_qty']}\n"
            f"❌ Difference: {report['drift']}\n"
            f"----------------------------------"
        )

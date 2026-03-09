import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class Reconciler:
    def __init__(self, ledger, tolerance: float = 0.0001):
        self.ledger = ledger
        self.tolerance = tolerance

    def reconcile_with_exchange(self, exchange_data: Dict[str, Any]) -> List[str]:
        """
        Automated Reconciliation: Compares Ledger vs Exchange and AUTO-FIXES drift.
        """
        # Ledger positions extraction
        ledger_positions = {
            sym: float(pos_obj.quantity)
            for sym, pos_obj in getattr(self.ledger, 'positions', {}).items()
        }

        incidents = self.reconcile_portfolio(ledger_positions, exchange_data)
        alert_messages = []

        for incident in incidents:
            symbol = incident['symbol']
            # --- AUTO-CORRECTION LOGIC ---
            # Ledger ko Exchange (Source of Truth) ke mutabiq update karein
            try:
                # Assuming exchange_data[symbol] contains 'side' (LONG/SHORT)
                side = exchange_data.get(symbol, {}).get('side', 'BOTH')
                self.ledger.update_position_manually(symbol, incident['exchange_qty'], side)
                logger.info(f"🔧 Auto-synced Ledger for {symbol} to {incident['exchange_qty']}")
            except Exception as e:
                logger.error(f"❌ Failed to auto-fix drift for {symbol}: {e}")

            alert_messages.append(self.format_incident(symbol, incident))

        return alert_messages

    def reconcile_portfolio(self, ledger_map: Dict[str, float], exchange_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        incidents = []
        actual_map = {sym: float(data['quantity']) for sym, data in exchange_data.items()}

        for symbol, expected_qty in ledger_map.items():
            actual_qty = actual_map.get(symbol, 0.0)
            report = self.detect_qty_drift(expected_qty, actual_qty)
            if not report["is_synced"]:
                report["symbol"] = symbol
                incidents.append(report)
            if symbol in actual_map:
                del actual_map[symbol]

        for symbol, actual_qty in actual_map.items():
            if abs(actual_qty) > self.tolerance:
                report = self.detect_qty_drift(0.0, actual_qty)
                report["symbol"] = symbol
                incidents.append(report)
        return incidents

    def detect_qty_drift(self, ledger_qty: float, exchange_qty: float) -> Dict[str, Any]:
        drift = abs(ledger_qty - exchange_qty)
        is_synced = drift <= self.tolerance
        return {
            "is_synced": is_synced,
            "drift": round(drift, 8),
            "ledger_qty": round(ledger_qty, 8),
            "exchange_qty": round(exchange_qty, 8),
        }

    def format_incident(self, symbol: str, report: Dict[str, Any]) -> str:
        return (
            f"🚨 *RECONCILIATION FIX: {symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Old Ledger:* `{report['ledger_qty']}`\n"
            f"📉 *Exchange:* `{report['exchange_qty']}`\n"
            f"🔧 *Status:* Ledger Synced to Exchange\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

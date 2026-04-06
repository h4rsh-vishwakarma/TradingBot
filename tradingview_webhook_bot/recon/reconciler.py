import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class Reconciler:
    def __init__(self, ledger=None, tolerance: float = 0.0001):
        self.ledger = ledger
        self.tolerance = tolerance

    def classify_drift(self, ledger_qty: float, exchange_qty: float, drift: float) -> tuple[str, str, str]:
        if drift <= self.tolerance:
            return "SYNCED", "OK", "No correction needed"

        if abs(exchange_qty) <= self.tolerance and abs(ledger_qty) > self.tolerance:
            return (
                "UNEXPECTED_FLAT",
                "HIGH",
                "Exchange was flat while ledger still showed exposure; ledger was flattened to exchange truth",
            )
        if abs(ledger_qty) <= self.tolerance and abs(exchange_qty) > self.tolerance:
            return (
                "UNEXPECTED_OPEN",
                "HIGH",
                "Exchange had open exposure while ledger was flat; ledger was opened to exchange truth",
            )
        if ledger_qty * exchange_qty < 0:
            return (
                "SIDE_MISMATCH",
                "CRITICAL",
                "Ledger and exchange were on opposite sides; ledger side/size was replaced with exchange truth",
            )

        max_abs = max(abs(ledger_qty), abs(exchange_qty), self.tolerance)
        drift_ratio = drift / max_abs
        severity = "MEDIUM" if drift_ratio < 0.25 else "HIGH"
        return (
            "POSITION_MISMATCH",
            severity,
            "Ledger quantity was synced to the exchange quantity",
        )

    def reconcile_with_exchange(self, exchange_data: Dict[str, Any]) -> List[str]:
        """
        Automated Reconciliation: Compares Ledger vs Exchange and AUTO-FIXES drift.

        KEY FORMAT NOTE:
        - Ledger keys:   "binance:BTCUSDT:strategy_name"  (exchange:symbol:strategy)
        - Exchange keys: "binance:BTCUSDT"                (exchange:symbol only)
        We aggregate all ledger positions for the same exchange:symbol before comparing.
        """
        # Aggregate ledger positions by "exchange:symbol" prefix (strip :strategy suffix)
        ledger_by_symbol: Dict[str, float] = {}
        for key, pos_obj in getattr(self.ledger, 'positions', {}).items():
            parts = key.split(':')
            # key format: exchange:symbol[:strategy] — take first two parts as base key
            base_key = ':'.join(parts[:2]) if len(parts) >= 2 else key
            ledger_by_symbol[base_key] = ledger_by_symbol.get(base_key, 0.0) + float(pos_obj.quantity)

        incidents = self.reconcile_portfolio(ledger_by_symbol, exchange_data)
        alert_messages = []

        for incident in incidents:
            symbol = incident['symbol']
            try:
                entry_price = incident.get('entry_price')
                if hasattr(self.ledger, "sync_symbol_from_exchange"):
                    self.ledger.sync_symbol_from_exchange(symbol, incident['exchange_qty'], avg_price=entry_price)
                else:
                    self.ledger.update_position_manually(symbol, incident['exchange_qty'], avg_price=entry_price)
                logger.info(f"🔧 Auto-synced Ledger for {symbol} to {incident['exchange_qty']} entry={entry_price}")
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
                # Carry entry_price from exchange_data so reconciler can sync it
                report["entry_price"] = exchange_data.get(symbol, {}).get("entry_price")
                incidents.append(report)
            if symbol in actual_map:
                del actual_map[symbol]

        for symbol, actual_qty in actual_map.items():
            if abs(actual_qty) > self.tolerance:
                report = self.detect_qty_drift(0.0, actual_qty)
                report["symbol"] = symbol
                report["entry_price"] = exchange_data.get(symbol, {}).get("entry_price")
                incidents.append(report)
        return incidents

    def detect_qty_drift(self, ledger_qty: float, exchange_qty: float) -> Dict[str, Any]:
        drift = abs(ledger_qty - exchange_qty)
        is_synced = drift <= self.tolerance
        drift_type, severity, correction = self.classify_drift(ledger_qty, exchange_qty, drift)
        return {
            "is_synced": is_synced,
            "drift_type": drift_type,
            "severity": severity,
            "drift": round(drift, 8),
            "ledger_qty": round(ledger_qty, 8),
            "exchange_qty": round(exchange_qty, 8),
            "correction": correction,
            "post_sync_qty": round(exchange_qty, 8),
        }

    def format_incident(self, symbol: str, report: Dict[str, Any]) -> str:
        entry_price = report.get("entry_price")
        entry_text = "n/a" if entry_price in (None, "", 0, 0.0) else str(entry_price)
        return (
            f"RECONCILIATION DRIFT FIXED: {symbol}\n"
            f"Type: {report['drift_type']}\n"
            f"Severity: {report['severity']}\n"
            f"Ledger Before: {report['ledger_qty']}\n"
            f"Exchange Before: {report['exchange_qty']}\n"
            f"Drift: {report['drift']}\n"
            f"Exchange Entry: {entry_text}\n"
            f"Correction: {report['correction']}\n"
            f"Ledger After: {report['post_sync_qty']}"
        )
        return (
            f"🚨 *RECONCILIATION FIX: {symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Old Ledger:* `{report['ledger_qty']}`\n"
            f"📉 *Exchange:* `{report['exchange_qty']}`\n"
            f"🔧 *Status:* Ledger Synced to Exchange\n"
            f"━━━━━━━━━━━━━━━━━━"
        )

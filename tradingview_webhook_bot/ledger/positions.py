"""
Deterministic Position Ledger
Calculates Weighted Average Entry Price (WAEP) and Realized PnL.
Persists state to local storage for crash recovery.
"""

import logging
import json
import os
from datetime import datetime
from typing import Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class PositionSnapshot(BaseModel):
    symbol: str
    quantity: float = 0.0      # Positive for LONG, Negative for SHORT
    avg_price: float = 0.0     # Weighted Average Entry Price
    realized_pnl: float = 0.0  # Total lifetime profit/loss
    daily_realized_pnl: float = 0.0 # PnL for the current day
    last_update_date: str = "" # To track PnL reset

class PositionLedger:
    def __init__(self, storage_path: str = "storage/ledger_state.json"):
        self.storage_path = storage_path
        self.positions: Dict[str, PositionSnapshot] = {}
        self._load_state()

    def _load_state(self):
        """Loads the previous ledger state from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                    for symbol, pos_data in data.items():
                        self.positions[symbol] = PositionSnapshot(**pos_data)
                logger.info(f"💾 Ledger state loaded from {self.storage_path}")
            except Exception as e:
                logger.error(f"❌ Failed to load ledger state: {e}")

    def _save_state(self):
        """Persists the current ledger state to disk."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w') as f:
                data = {s: p.model_dump() for s, p in self.positions.items()}
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save ledger state: {e}")

    def get_daily_pnl(self) -> float:
        """
        Calculates total realized PnL for all symbols for the current UTC day.
        """
        today = datetime.utcnow().strftime('%Y-%m-%d')
        total_daily_pnl = 0.0
        
        for symbol, pos in self.positions.items():
            # Reset logic: If last update was not today, daily PnL is effectively 0
            if pos.last_update_date == today:
                total_daily_pnl += pos.daily_realized_pnl
        
        return total_daily_pnl

    def apply_fill(self, symbol: str, side: str, qty: float, price: float, fee: float = 0.0):
        """
        Updates the ledger based on a trade fill and tracks Daily PnL.
        """
        if symbol not in self.positions:
            self.positions[symbol] = PositionSnapshot(symbol=symbol)

        pos = self.positions[symbol]
        today = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Reset Daily PnL if it's a new day
        if pos.last_update_date != today:
            pos.daily_realized_pnl = 0.0
            pos.last_update_date = today

        side = side.lower()
        trade_qty = qty if side == 'buy' else -qty
        is_increasing = (pos.quantity >= 0 and trade_qty > 0) or (pos.quantity <= 0 and trade_qty < 0)

        trade_pnl = 0.0
        if is_increasing:
            new_total_qty = pos.quantity + trade_qty
            if abs(new_total_qty) > 1e-10:
                pos.avg_price = ((abs(pos.quantity) * pos.avg_price) + (qty * price)) / abs(new_total_qty)
            pos.quantity = new_total_qty
            trade_pnl = -fee
        else:
            direction = 1 if pos.quantity > 0 else -1
            realized_qty = min(abs(pos.quantity), qty)
            trade_pnl = ((price - pos.avg_price) * realized_qty * direction) - fee
            pos.quantity += trade_qty

            if abs(pos.quantity) < 1e-10:
                pos.quantity = 0.0
                pos.avg_price = 0.0
            elif (direction == 1 and pos.quantity < 0) or (direction == -1 and pos.quantity > 0):
                pos.avg_price = price

        pos.realized_pnl += trade_pnl
        pos.daily_realized_pnl += trade_pnl
        
        self._save_state()
        logger.info(f"📊 Ledger Updated | {symbol} | Daily PnL: ${self.get_daily_pnl():.2f}")
        return pos

    def update_position_manually(self, symbol: str, quantity: float):
        if symbol not in self.positions:
            self.positions[symbol] = PositionSnapshot(symbol=symbol)
        pos = self.positions[symbol]
        pos.quantity = float(quantity)
        if abs(pos.quantity) < 1e-10:
            pos.avg_price = 0.0
        self._save_state()

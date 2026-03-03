"""
Deterministic Position Ledger
Calculates Weighted Average Entry Price (WAEP) and Realized PnL.
Persists state to local storage for crash recovery.
"""

import logging
import json
import os
from typing import Dict
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class PositionSnapshot(BaseModel):
    symbol: str
    quantity: float = 0.0      # Positive for LONG, Negative for SHORT
    avg_price: float = 0.0     # Weighted Average Entry Price
    realized_pnl: float = 0.0  # Total profit/loss after fees

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
                # Convert Pydantic models to dict for JSON serialization
                data = {s: p.model_dump() for s, p in self.positions.items()}
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"❌ Failed to save ledger state: {e}")

    def apply_fill(self, symbol: str, side: str, qty: float, price: float, fee: float = 0.0):
        """
        Updates the ledger based on a trade fill.
        Supports both Long and Short position logic.
        """
        if symbol not in self.positions:
            self.positions[symbol] = PositionSnapshot(symbol=symbol)

        pos = self.positions[symbol]
        side = side.lower()
        
        # Determine trade direction: Buy adds to qty, Sell subtracts from qty
        trade_qty = qty if side == 'buy' else -qty

        # Logic for Opening or Increasing a Position (Buying more Long or Selling more Short)
        # If current qty and trade qty are in the same direction, update Average Price
        is_increasing = (pos.quantity >= 0 and trade_qty > 0) or (pos.quantity <= 0 and trade_qty < 0)

        if is_increasing:
            new_total_qty = pos.quantity + trade_qty
            if abs(new_total_qty) > 0:
                # Formula: WAEP = (CurrentValue + NewValue) / TotalQty
                pos.avg_price = ((abs(pos.quantity) * pos.avg_price) + (qty * price)) / abs(new_total_qty)
            pos.quantity = new_total_qty
            pos.realized_pnl -= fee
        
        # Logic for Closing or Reducing a Position (Realizing PnL)
        else:
            # PnL = (Exit Price - Entry Price) * Qty * Direction
            direction = 1 if pos.quantity > 0 else -1
            realized_qty = min(abs(pos.quantity), qty)
            
            trade_pnl = (price - pos.avg_price) * realized_qty * direction
            pos.realized_pnl += (trade_pnl - fee)
            
            # Update remaining quantity
            pos.quantity += trade_qty
            
            # If position is flipped or closed, reset/update price
            if abs(pos.quantity) < 1e-10: # Near zero
                pos.quantity = 0.0
                pos.avg_price = 0.0
            elif (direction == 1 and pos.quantity < 0) or (direction == -1 and pos.quantity > 0):
                # Position flipped (Long to Short or vice versa)
                pos.avg_price = price

        self._save_state()
        logger.info(f"📊 Ledger Updated | {symbol} | Pos: {pos.quantity} | WAEP: {pos.avg_price:.2f} | PnL: {pos.realized_pnl:.4f}")
        return pos

    def get_position(self, symbol: str) -> PositionSnapshot:
        return self.positions.get(symbol, PositionSnapshot(symbol=symbol))

    def get_all_positions(self) -> Dict[str, float]:
        """Returns a simple map for Reconciliation Engine."""
        return {symbol: pos.quantity for symbol, pos in self.positions.items()}

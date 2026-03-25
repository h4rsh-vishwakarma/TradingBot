"""
Deterministic Position Ledger
Calculates Weighted Average Entry Price (WAEP) and Realized PnL.
Persists state to local storage for crash recovery and Hybrid Scoring.
"""

import logging
import json
import os
import tempfile
from datetime import datetime
from typing import Dict, List
from pydantic import BaseModel

try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False  # Windows

logger = logging.getLogger(__name__)

class PositionSnapshot(BaseModel):
    symbol: str
    quantity: float = 0.0      # Positive for LONG, Negative for SHORT
    avg_price: float = 0.0      # Weighted Average Entry Price
    realized_pnl: float = 0.0  # Total lifetime profit/loss
    daily_realized_pnl: float = 0.0 # PnL for the current day
    last_update_date: str = "" # To track PnL reset

class PositionLedger:
    def __init__(self, storage_path: str = "storage/ledger_state.json"):
        self.storage_path = storage_path
        self.positions: Dict[str, PositionSnapshot] = {}
        # ⭐ New: Trade history for Hybrid Scoring (Live performance)
        self.trade_history: List[dict] = [] 
        self._load_state()

    def _load_state(self):
        """Loads the previous ledger state from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, 'r') as f:
                    full_data = json.load(f)
                    # Support for both old and new storage formats
                    pos_data = full_data.get("positions", full_data) if isinstance(full_data, dict) else {}
                    self.trade_history = full_data.get("trade_history", []) if isinstance(full_data, dict) else []
                    
                    for symbol, data in pos_data.items():
                        self.positions[symbol] = PositionSnapshot(**data)
                logger.info(f"💾 Ledger state loaded. History: {len(self.trade_history)} trades.")
            except Exception as e:
                logger.error(f"❌ Failed to load ledger state: {e}")

    def _save_state(self):
        """Persists the current ledger state atomically with file locking."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            data = {
                "positions": {s: p.model_dump() for s, p in self.positions.items()},
                "trade_history": self.trade_history[-50:]
            }
            # Atomic write: write to temp file, then rename
            dir_name = os.path.dirname(self.storage_path)
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    if HAS_FCNTL:
                        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    json.dump(data, f, indent=4)
                os.replace(tmp_path, self.storage_path)
            except Exception:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                raise
        except Exception as e:
            logger.error(f"❌ Failed to save ledger state: {e}")

    def get_position(self, symbol: str) -> PositionSnapshot:
        """Returns snapshot for a symbol."""
        return self.positions.get(symbol, PositionSnapshot(symbol=symbol))

    def get_daily_pnl(self) -> float:
        """Calculates total realized PnL for the current day."""
        today = datetime.utcnow().strftime('%Y-%m-%d')
        total_daily_pnl = 0.0
        for pos in self.positions.values():
            if pos.last_update_date == today:
                total_daily_pnl += pos.daily_realized_pnl
        return total_daily_pnl

    # ⭐ NEW FEATURE: Hybrid Scoring Support
    def get_daily_pnl_events(self) -> List[dict]:
        """Returns trade history for Hybrid scoring engine."""
        return self.trade_history

    def apply_fill(self, symbol: str, side: str, qty: float, price: float, fee: float = 0.0):
        """Core logic to update WAEP and track realized PnL."""
        if symbol not in self.positions:
            self.positions[symbol] = PositionSnapshot(symbol=symbol)

        pos = self.positions[symbol]
        today = datetime.utcnow().strftime('%Y-%m-%d')

        # Reset daily PnL if new day
        if pos.last_update_date != today:
            pos.daily_realized_pnl = 0.0
            pos.last_update_date = today

        side = side.lower()
        trade_qty = qty if side == 'buy' else -qty
        
        # Check if trade increases or reduces position
        is_increasing = (pos.quantity >= 0 and trade_qty > 0) or (pos.quantity <= 0 and trade_qty < 0)

        trade_pnl = 0.0
        if is_increasing:
            # Weighted Average Entry Price logic
            new_total_qty = pos.quantity + trade_qty
            if abs(new_total_qty) > 1e-10:
                pos.avg_price = ((abs(pos.quantity) * pos.avg_price) + (qty * price)) / abs(new_total_qty)
            pos.quantity = new_total_qty
            trade_pnl = -fee
        else:
            # Profit calculation for closing/reducing
            direction = 1 if pos.quantity > 0 else -1
            realized_qty = min(abs(pos.quantity), qty)
            trade_pnl = ((price - pos.avg_price) * realized_qty * direction) - fee
            
            # Record trade in history for Hybrid scoring
            self.trade_history.append({
                "timestamp": datetime.utcnow().isoformat(),
                "symbol": symbol,
                "pnl": trade_pnl,
                "exit_price": price
            })
            
            pos.quantity += trade_qty
            if abs(pos.quantity) < 1e-10:
                pos.quantity = 0.0
                pos.avg_price = 0.0
            elif (direction == 1 and pos.quantity < 0) or (direction == -1 and pos.quantity > 0):
                # Flit: Position reversed (Long to Short or vice versa)
                pos.avg_price = price

        pos.realized_pnl += trade_pnl
        pos.daily_realized_pnl += trade_pnl
        self._save_state()
        return pos

    def update_position_manually(self, symbol: str, quantity: float):
        """Force update position (Reconciliation fallback)."""
        if symbol not in self.positions:
            self.positions[symbol] = PositionSnapshot(symbol=symbol)
        pos = self.positions[symbol]
        pos.quantity = float(quantity)
        if abs(pos.quantity) < 1e-10:
            pos.avg_price = 0.0
        self._save_state()

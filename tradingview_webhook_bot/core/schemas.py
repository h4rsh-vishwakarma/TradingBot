"""
Canonical Schemas for the Trading Bot.
Standardizes data models across Webhook, Orchestrator, and Ledger.
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from enum import Enum
from datetime import datetime

class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class SignalPayload(BaseModel):
    secret: str = ""   # optional — no longer required for authentication
    strategy: str
    symbol: str
    action: TradeAction
    quantity: float
    price: float
    indicator: Optional[str] = "N/A"
    strategy_id: str = "default"

class SignalRecord(BaseModel):
    signal_id: str
    timestamp: datetime
    status: str = "received"
    payload: SignalPayload

class PositionSnapshot(BaseModel):
    symbol: str
    position_size: float = 0.0
    entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    last_update: datetime = Field(default_factory=datetime.utcnow)

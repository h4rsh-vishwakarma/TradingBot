from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum
from datetime import datetime

class SignalStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

class TradingViewPayload(BaseModel):
    secret: str
    strategy: str
    symbol: str
    action: str
    quantity: float
    price: float
    indicator: Optional[str] = "N/A"

class SignalEvent(BaseModel):
    signal_id: str
    received_at: datetime = Field(default_factory=datetime.utcnow)
    status: SignalStatus = SignalStatus.PENDING
    payload: TradingViewPayload
    error_msg: Optional[str] = None

class FillEvent(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    fee: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

from pydantic import BaseModel, Field, field_validator
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime

class ActionEnum(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class SignalStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class TradingViewPayload(BaseModel):
    """TradingView se aane wale raw data ka schema."""
    symbol: str = Field(..., example="BTCUSDT")
    action: ActionEnum
    quantity: float = Field(..., gt=0)
    price: float = Field(..., gt=0)
    strategy: str = Field(default="default_strategy")
    sl_percent: Optional[float] = Field(None, ge=0)
    tp_percent: Optional[float] = Field(None, ge=0)

    @field_validator('symbol')
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.upper()

class SignalEvent(BaseModel):
    """Internal system mein use hone wala full event model."""
    signal_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: TradingViewPayload
    status: SignalStatus = SignalStatus.RECEIVED

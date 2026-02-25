from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime

class SignalStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    IDEMPOTENT_SKIP = "idempotent_skip"

class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

class SignalEvent(BaseModel):
    signal_id: str
    strategy_id: str
    symbol: str
    action: str  # buy/sell/long/short
    quantity: float
    price: float
    received_at: datetime = Field(default_factory=datetime.utcnow)
    status: SignalStatus = SignalStatus.RECEIVED
    raw_payload: Dict[str, Any]

    @field_validator('strategy_id', mode='before') # Updated syntax
    @classmethod
    def clean_strategy_name(cls, v):
        if not isinstance(v, str):
            return v
        if "Smart Money Concepts" in v:
            return "luxalgo_smc"
        return v.lower().replace(" ", "_")

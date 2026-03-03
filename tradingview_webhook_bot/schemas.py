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

# --- UPDATED: Payload Schema to include Indicators & Strategy ID ---
class TradingViewPayload(BaseModel):
    symbol: str
    action: str  # buy/sell/long/short/tp
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    strategy: str = "default"  # Legacy support
    strategy_id: Optional[str] = "default"  # New field for reporting
    indicator: Optional[str] = "N/A"        # New field for technicals
    secret: Optional[str] = None

class SignalEvent(BaseModel):
    signal_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: SignalStatus = SignalStatus.RECEIVED
    payload: TradingViewPayload 

    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    def model_dump_json(self, **kwargs):
        return self.model_dump(mode='json', **kwargs)

# --- Compatibility Layer ---
class SignalEventLegacy(SignalEvent):
    @property
    def strategy_id(self):
        # Prefer strategy_id if provided, else fallback to strategy
        v = self.payload.strategy_id or self.payload.strategy
        if "Smart Money Concepts" in v:
            return "luxalgo_smc"
        return v.lower().replace(" ", "_")

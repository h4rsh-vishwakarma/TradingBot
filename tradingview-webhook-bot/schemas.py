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
    CAN_CELLED = "cancelled"
    REJECTED = "rejected"

# --- NEW: Senior ki requirement ke mutabiq Payload Schema ---
class TradingViewPayload(BaseModel):
    symbol: str
    action: str  # buy/sell/long/short
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    strategy: str = "default"
    secret: Optional[str] = None

class SignalEvent(BaseModel):
    signal_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: SignalStatus = SignalStatus.RECEIVED
    payload: TradingViewPayload  # Linking the payload model
    
    # Validation ke liye strategy_id helper (Agar aapko alag se chahiye)
    @field_validator('status', mode='before')
    @classmethod
    def validate_status(cls, v):
        if isinstance(v, str):
            return v.lower()
        return v

    def model_dump_json(self, **kwargs):
        # Senior's Atomic Enqueue requirement: mode='json'
        return self.model_dump(mode='json', **kwargs)

# --- Compatibility Layer ---
# Agar aapka purana code strategy_id dhund raha hai
class SignalEventLegacy(SignalEvent):
    @property
    def strategy_id(self):
        v = self.payload.strategy
        if "Smart Money Concepts" in v:
            return "luxalgo_smc"
        return v.lower().replace(" ", "_")

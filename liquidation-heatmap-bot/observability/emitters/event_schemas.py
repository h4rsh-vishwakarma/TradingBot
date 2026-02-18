"""Event schemas and enums for the observability system.

Defines canonical event structures for:
- decision, guard, veto, order, fill, health, error

All events include: ts, run_id, session_id, venue, symbol, env, mode
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional, Any, List
import uuid
import os
import json


# ============================================================================
# ENUMS
# ============================================================================

class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class SignalStrength(str, Enum):
    STRONG = "STRONG"
    MEDIUM = "MEDIUM"
    NONE = "NONE"


class Action(str, Enum):
    NO_TRADE = "NO_TRADE"
    PLACE = "PLACE"
    AMEND = "AMEND"
    CANCEL = "CANCEL"


class NoTradeReason(str, Enum):
    STALE_FEED = "stale_feed"
    INSUFFICIENT_EDGE = "insufficient_edge"
    CAPACITY_FULL = "capacity_full"
    CONTEXT_VETO = "context_veto"
    MIN_NOTIONAL = "min_notional"
    MIN_QTY = "min_qty"
    STEP_VIOLATION = "step_violation"
    TICK_VIOLATION = "tick_violation"
    TIE_UNRESOLVED = "tie_unresolved"
    SPREAD_TOO_WIDE = "spread_too_wide"
    SLIPPAGE_TOO_HIGH = "slippage_too_high"
    DAILY_CAP_HIT = "daily_cap_hit"
    COOLDOWN_ACTIVE = "cooldown_active"
    KILL_SWITCH = "kill_switch"
    NO_CLUSTERS = "no_clusters"
    NO_SIGNAL = "no_signal"


class GuardKind(str, Enum):
    STALE_PRICE = "STALE_PRICE"
    STALE_HEATMAP = "STALE_HEATMAP"
    STALE_DATA = "STALE_DATA"
    DAILY_CAP_HIT = "DAILY_CAP_HIT"
    INFRA_DEGRADED = "INFRA_DEGRADED"
    WS_DISCONNECTED = "WS_DISCONNECTED"
    INSUFFICIENT_EDGE = "INSUFFICIENT_EDGE"
    CAPACITY_FULL = "CAPACITY_FULL"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    KILL_SWITCH = "KILL_SWITCH"
    OTHER = "OTHER"


class VetoReason(str, Enum):
    RISK_CAP = "RISK_CAP"
    ORDER_REJECT = "ORDER_REJECT"
    ENGINE_ERROR = "ENGINE_ERROR"
    STALE_DATA = "STALE_DATA"
    EDGE_TOO_SMALL = "EDGE_TOO_SMALL"
    FUNDING_EXTREME = "FUNDING_EXTREME"
    OI_MISALIGNED = "OI_MISALIGNED"
    POST_SHOCK = "POST_SHOCK"
    FUNDING_WINDOW = "FUNDING_WINDOW"
    REGIME_UNFAVORABLE = "REGIME_UNFAVORABLE"
    VOLATILITY_EXTREME = "VOLATILITY_EXTREME"
    CLUSTER_TOO_FAR = "CLUSTER_TOO_FAR"
    CLUSTER_TOO_WEAK = "CLUSTER_TOO_WEAK"
    POSITION_LIMIT = "POSITION_LIMIT"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_MARKET = "STOP_MARKET"
    TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"


class OrderStatus(str, Enum):
    NEW = "NEW"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class Severity(str, Enum):
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


# ============================================================================
# BASE EVENT
# ============================================================================

@dataclass
class BaseEvent:
    """Base event with common fields required by all events."""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str = field(default_factory=lambda: os.getenv('RUN_ID', f'r_{uuid.uuid4().hex[:8]}'))
    session_id: str = field(default_factory=lambda: os.getenv('SESSION_ID', f's_{uuid.uuid4().hex[:8]}'))
    venue: str = "binanceusdm"
    symbol: str = "BTCUSDT"
    env: str = field(default_factory=lambda: os.getenv('ENV', 'dev'))
    mode: str = field(default_factory=lambda: os.getenv('TRADING_MODE', 'PAPER'))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ============================================================================
# CLUSTER SUB-OBJECT
# ============================================================================

@dataclass
class ClusterInfo:
    """Cluster information for decision events."""
    timeframe: str = ""
    target_level: float = 0.0
    target_width_pct: float = 0.0
    intensity_z: float = 0.0
    distance_bps: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# CONTEXT SUB-OBJECT
# ============================================================================

@dataclass
class ContextInfo:
    """Market context for decision events."""
    oi_delta_30m_bps: float = 0.0
    funding_pct: float = 0.0
    lsr: float = 1.0  # Long/Short ratio
    post_shock_flag: bool = False
    funding_window_block: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# COSTS SUB-OBJECT
# ============================================================================

@dataclass
class CostsInfo:
    """Cost/edge analysis for decision events."""
    spread_bps: float = 0.0
    est_slip_bps: float = 0.0
    edge_bps: float = 0.0
    edge_ok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# RISK SUB-OBJECT
# ============================================================================

@dataclass
class RiskInfo:
    """Risk parameters for decision events."""
    risk_R_pct: float = 0.0
    sl_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# ORDERABILITY SUB-OBJECT
# ============================================================================

@dataclass
class OrderabilityInfo:
    """Order validation checks for decision events."""
    qty: float = 0.0
    step_ok: bool = True
    tick_ok: bool = True
    minQty_ok: bool = True
    minNotional_ok: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# VOTES SUB-OBJECT
# ============================================================================

@dataclass
class VotesInfo:
    """Voting system results for decision events."""
    m1: str = "NONE"  # m1_proximity
    m2: str = "NONE"  # m2_density
    m3: str = "NONE"  # m3_sentiment

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# DECISION EVENT
# ============================================================================

@dataclass
class DecisionEvent(BaseEvent):
    """Decision event - emitted for every signal evaluation."""
    event: str = "decision"
    decision_id: str = field(default_factory=lambda: f"dec_{uuid.uuid4().hex[:8]}")
    
    # Signal
    signal_dir: str = "NONE"
    signal_strength: str = "NONE"
    S_long: float = 0.0
    S_short: float = 0.0
    votes: Dict[str, str] = field(default_factory=lambda: {"m1": "NONE", "m2": "NONE", "m3": "NONE"})
    tie_break_used: bool = False
    
    # P1: Enhanced vote scoring (1-100 confidence per timeframe)
    vote_scores: Dict[str, float] = field(default_factory=lambda: {"m1": 0.0, "m2": 0.0, "m3": 0.0})
    
    # Cluster
    cluster: Dict[str, Any] = field(default_factory=dict)
    
    # P1: Cluster ranking for LLM training (1=highest conviction)
    cluster_rank: int = 0
    
    # P1: Precise entry price for execution tracking
    entry_px: float = 0.0
    
    # Context
    context: Dict[str, Any] = field(default_factory=dict)
    
    # Costs
    costs: Dict[str, Any] = field(default_factory=dict)
    
    # Risk
    risk: Dict[str, Any] = field(default_factory=dict)
    
    # Orderability
    orderability: Dict[str, Any] = field(default_factory=dict)
    
    # Action
    action: str = "NO_TRADE"
    no_trade_reason: Optional[str] = None
    
    # Timing
    latency_ms: float = 0.0
    
    # Sampling flag (for slim vs full)
    is_full_sample: bool = False


# ============================================================================
# GUARD EVENT
# ============================================================================

@dataclass
class GuardEvent(BaseEvent):
    """Guard event - emitted when a guard condition triggers."""
    event: str = "guard"
    kind: str = "other"  # stale, edge, capacity, other
    details: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# VETO EVENT
# ============================================================================

@dataclass
class VetoEvent(BaseEvent):
    """Veto event - emitted when context vetoes a trade."""
    event: str = "veto.context"
    reason: str = ""  # funding_extreme, oi_misaligned, post_shock, funding_window
    fields: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# ORDER EVENT
# ============================================================================

@dataclass
class OrderEvent(BaseEvent):
    """Order event - emitted when an order is placed/updated."""
    event: str = "order"
    order_id: str = ""
    decision_id: str = ""
    side: str = "BUY"
    type: str = "MARKET"
    px: float = 0.0
    qty: float = 0.0
    status: str = "NEW"
    latency_ms: float = 0.0
    reduce_only: bool = False
    time_in_force: str = "GTC"


# ============================================================================
# FILL EVENT
# ============================================================================

@dataclass
class FillEvent(BaseEvent):
    """Fill event - emitted when an order is filled."""
    event: str = "fill"
    fill_id: str = field(default_factory=lambda: f"fill_{uuid.uuid4().hex[:8]}")
    order_id: str = ""
    decision_id: str = ""  # P3: Link fill to decision for analysis
    px: float = 0.0
    qty: float = 0.0
    fee: float = 0.0
    pnl_open: float = 0.0
    pnl_close: float = 0.0
    expected_px: Optional[float] = None  # P3: Expected price from decision/order
    slippage_bps: Optional[float] = None  # P3: (fill_px - expected_px) / expected_px * 10000


# ============================================================================
# HEALTH EVENT
# ============================================================================

@dataclass
class HealthEvent(BaseEvent):
    """Health event - emitted periodically for system health monitoring."""
    event: str = "health.heartbeat"
    price_age_s: Optional[float] = None
    price_age_s_ws: Optional[float] = None  # P0: WebSocket price age for precise feed discrimination
    price_age_s_rest: Optional[float] = None  # P0: REST API price age for precise feed discrimination
    heatmap_age_s: Optional[float] = None
    ws_connected: bool = False
    coinglass_ok: bool = True
    positions_open: int = 0
    risk_used_pct: float = 0.0
    risk_remaining_usd: Optional[float] = None  # P0: Remaining risk budget in USD
    daily_cap_hit: bool = False
    daily_cap_hit_ts: Optional[str] = None  # P0: Timestamp when daily cap was hit for correlation analysis
    kill_switch_active: bool = False  # P1: Kill switch state
    kill_switch_reason: Optional[str] = None  # P1: Reason for kill switch activation
    kill_switch_trigger_ts: Optional[str] = None  # P1: Timestamp when kill switch was triggered
    equity_usd: float = 0.0
    pnl_realized_usd: float = 0.0
    pnl_unrealized_usd: float = 0.0  # Unrealized PnL from open positions
    risk_per_position_usd: Optional[List[float]] = None  # P0: Risk per position for concentration monitoring


# ============================================================================
# ERROR EVENT
# ============================================================================

@dataclass
class ErrorEvent(BaseEvent):
    """Error event - emitted when an error occurs."""
    event: str = "error"
    severity: str = "ERROR"  # WARN, ERROR, CRITICAL
    component: str = ""
    message: str = ""
    exc_type: Optional[str] = None
    exc_msg: Optional[str] = None
    stack: Optional[str] = None
    decision_id: Optional[str] = None
    order_id: Optional[str] = None


# ============================================================================
# SLIM SCHEMA FOR SAMPLING
# ============================================================================

SLIM_DECISION_FIELDS = [
    'ts', 'run_id', 'session_id', 'venue', 'symbol', 'env', 'mode',
    'decision_id', 'signal_dir', 'signal_strength', 'S_long', 'S_short',
    'votes', 'cluster', 'action', 'no_trade_reason', 'latency_ms'
]


def slim_decision(event: DecisionEvent) -> Dict[str, Any]:
    """Extract slim schema from a full decision event."""
    full = event.to_dict()
    return {k: full.get(k) for k in SLIM_DECISION_FIELDS if k in full}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_run_id() -> str:
    """Generate a new run ID."""
    return f"r_{uuid.uuid4().hex[:8]}"


def generate_session_id() -> str:
    """Generate a new session ID."""
    return f"s_{uuid.uuid4().hex[:8]}"


def generate_decision_id() -> str:
    """Generate a new decision ID."""
    return f"dec_{uuid.uuid4().hex[:8]}"


def generate_order_id() -> str:
    """Generate a new order ID."""
    return f"ord_{uuid.uuid4().hex[:8]}"


def generate_fill_id() -> str:
    """Generate a new fill ID."""
    return f"fill_{uuid.uuid4().hex[:8]}"

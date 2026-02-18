# observability/emitters/llm_summary_emitter.py
"""
LLM-optimized summary emitter for trading events.
Emits compact, chunked JSONL.gz files tuned for LLM ingestion.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class TradeSummary:
    """Per-trade summary optimized for LLM analysis."""
    ts_open: str
    ts_close: Optional[str]
    decision_id: str
    side: str
    entry_px: float
    exit_px: Optional[float]
    qty: float
    r_multiple: Optional[float]
    pnl_usd: Optional[float]
    edge_bps_at_entry: Optional[float] = None
    cluster_width_bps: Optional[float] = None
    cluster_intensity_z: Optional[float] = None
    regime_tag: Optional[str] = None
    exit_reason: Optional[str] = None
    hold_duration_s: Optional[float] = None
    veto_reasons: Optional[List[str]] = None
    guard_kinds: Optional[List[str]] = None


@dataclass
class SessionSummary:
    """Per-session/day summary for high-level LLM context."""
    session_id: str
    run_id: str
    session_start_ts: str
    session_end_ts: str
    duration_s: float
    n_decisions: int
    n_trades: int
    n_no_trades: int
    total_pnl_usd: float
    win_rate: float
    avg_r_multiple: Optional[float]
    max_drawdown_usd: Optional[float]
    daily_cap_hit: bool
    top_veto_reasons: Dict[str, int]
    top_guard_kinds: Dict[str, int]
    top_no_trade_reasons: Dict[str, int]
    positions_peak: int
    equity_start_usd: float
    equity_end_usd: float
    data_quality_score: Optional[float] = None


class LLMSummaryEmitter:
    """
    Tier-2 emitter for LLM-friendly summaries.
    
    Produces small, chunked JSONL.gz files under logs/llm_summaries/
    with trade-level and session-level summaries.
    """
    
    def __init__(self, output_dir: str = "logs/llm_summaries", chunk_max_lines: int = 5000):
        """
        Initialize LLM summary emitter.
        
        Args:
            output_dir: Directory for summary files
            chunk_max_lines: Max lines per chunk file (default 5000 for ~5-10MB files)
        """
        self.output_dir = Path(output_dir)
        self.chunk_max_lines = chunk_max_lines
        
        # Separate buffers for trades and sessions
        self._trade_buffer: List[Dict[str, Any]] = []
        self._session_buffer: List[Dict[str, Any]] = []
        
        # Chunk indices
        self._trade_chunk_idx = 0
        self._session_chunk_idx = 0
        
        # Create output directories
        self.trades_dir = self.output_dir / "trades"
        self.sessions_dir = self.output_dir / "sessions"
        self.trades_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
    
    def emit_trade(self, summary: TradeSummary):
        """Add a trade summary to buffer and flush if needed."""
        self._trade_buffer.append(asdict(summary))
        if len(self._trade_buffer) >= self.chunk_max_lines:
            self.flush_trades()
    
    def emit_session(self, summary: SessionSummary):
        """Add a session summary to buffer and flush if needed."""
        self._session_buffer.append(asdict(summary))
        if len(self._session_buffer) >= 100:  # Sessions are fewer, flush at 100
            self.flush_sessions()
    
    def flush_trades(self):
        """Write trade buffer to disk as compressed JSONL."""
        if not self._trade_buffer:
            return
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"trade_summaries_{self._trade_chunk_idx:04d}_{timestamp}.jsonl.gz"
        path = self.trades_dir / filename
        
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for row in self._trade_buffer:
                f.write(json.dumps(row, default=str) + "\n")
        
        self._trade_buffer.clear()
        self._trade_chunk_idx += 1
    
    def flush_sessions(self):
        """Write session buffer to disk as compressed JSONL."""
        if not self._session_buffer:
            return
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"session_summaries_{self._session_chunk_idx:04d}_{timestamp}.jsonl.gz"
        path = self.sessions_dir / filename
        
        with gzip.open(path, "wt", encoding="utf-8") as f:
            for row in self._session_buffer:
                f.write(json.dumps(row, default=str) + "\n")
        
        self._session_buffer.clear()
        self._session_chunk_idx += 1
    
    def flush_all(self):
        """Flush all buffers (call on shutdown)."""
        self.flush_trades()
        self.flush_sessions()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get emitter statistics."""
        return {
            "trades_buffered": len(self._trade_buffer),
            "sessions_buffered": len(self._session_buffer),
            "trade_chunks_written": self._trade_chunk_idx,
            "session_chunks_written": self._session_chunk_idx,
            "output_dir": str(self.output_dir)
        }

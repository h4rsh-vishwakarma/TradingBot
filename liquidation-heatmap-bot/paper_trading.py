"""
Paper Trading Simulator Module
Simulates real-time trading without actual API calls
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

@dataclass
class PaperPosition:
    """Paper trading position"""
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    timestamp: datetime
    confidence: float
    risk_amount: float
    unrealized_pnl: float = 0.0
    status: str = "OPEN"  # "OPEN", "CLOSED", "STOPPED", "TAKE_PROFIT"
    # Decision tracking for observability
    decision_id: Optional[str] = None
    # Optional metadata for analytics
    entry_mode: Optional[str] = None  # e.g., FADE or CONTINUE
    signal_type: Optional[str] = None
    regime: Optional[str] = None
    multi_tf_score: Optional[float] = None
    cluster_width_pct: Optional[float] = None
    cluster_intensity_z: Optional[float] = None
    edge_bps: Optional[float] = None  # Edge in basis points at entry
    veto_reasons: Optional[List[str]] = None
    guard_kinds: Optional[List[str]] = None

@dataclass
class PaperTrade:
    """Completed paper trade"""
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    entry_time: datetime
    exit_time: datetime
    pnl: float
    pnl_percentage: float
    exit_reason: str
    confidence: float
    # Optional analytics fields
    risk_amount: Optional[float] = None
    entry_mode: Optional[str] = None
    signal_type: Optional[str] = None
    regime: Optional[str] = None
    multi_tf_score: Optional[float] = None
    cluster_width_pct: Optional[float] = None
    cluster_intensity_z: Optional[float] = None

class PaperTradingSimulator:
    """Simulates real-time trading with realistic market conditions"""
    
    def __init__(self, config, emitters=None, risk_manager=None, exit_callback=None):
        self.config = config
        self.trading_config = config.get_trading_config()
        self.emitters = emitters  # ObservabilityHub for trade summaries
        self.risk_manager = risk_manager  # TIER 1: Wire risk manager for PnL tracking
        self.exit_callback = exit_callback  # Callback to signal_generator for exit fill logging
        
        # Account state
        self.balance = self.trading_config.initial_balance
        self.initial_balance = self.trading_config.initial_balance
        self.max_balance = self.initial_balance
        
        # Position management
        self.open_positions: List[PaperPosition] = []
        self.closed_trades: List[PaperTrade] = []
        
        # Market data simulation
        self.current_price = 50000.0  # Starting BTC price
        self.price_history = deque(maxlen=1000)
        self.volatility = 0.02  # 2% daily volatility
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        
        # Simulation parameters
        self.slippage_factor = 0.0005  # 0.05% slippage
        self.commission_rate = 0.0004  # 0.04% commission (Binance futures)
        self.spread_factor = 0.0002    # 0.02% spread
        
        # Price simulation thread
        self.price_simulation_running = False
        self.price_thread = None
        
        logger.info(f"Paper Trading Simulator initialized with ${self.balance:,.2f}")
    
    def start_price_simulation(self, initial_price: float = None):
        """Start price simulation thread"""
        if initial_price:
            self.current_price = initial_price
        
        self.price_simulation_running = True
        self.price_thread = threading.Thread(target=self._simulate_price_movement, daemon=True)
        self.price_thread.start()
        logger.info(f"Price simulation started at ${self.current_price:,.2f}")
    
    def stop_price_simulation(self):
        """Stop price simulation thread"""
        self.price_simulation_running = False
        if self.price_thread:
            self.price_thread.join(timeout=1)
        logger.info("Price simulation stopped")
    
    def _simulate_price_movement(self):
        """Simulate realistic price movement"""
        while self.price_simulation_running:
            try:
                # Generate price movement using geometric Brownian motion
                dt = 1.0 / (24 * 60)  # 1 minute intervals
                drift = 0.0001  # Small upward drift
                shock = np.random.normal(0, self.volatility * np.sqrt(dt))
                
                # Calculate new price
                price_change = self.current_price * (drift * dt + shock)
                new_price = self.current_price + price_change
                
                # Ensure price doesn't go negative
                new_price = max(new_price, 1000.0)
                
                # Update price
                self.current_price = new_price
                self.price_history.append({
                    'timestamp': datetime.now(),
                    'price': self.current_price
                })
                
                # Update open positions
                self._update_open_positions()
                
                # Sleep for 1 second (simulating 1-minute intervals)
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in price simulation: {e}")
                time.sleep(1)
    
    def _update_open_positions(self):
        """Update unrealized P&L for open positions"""
        # Debug logging every 100 price updates to avoid spam
        if not hasattr(self, '_update_counter'):
            self._update_counter = 0
        self._update_counter += 1
        
        if self._update_counter % 100 == 0 and len(self.open_positions) > 0:
            logger.info(f"🔍 Monitoring {len(self.open_positions)} open positions at price=${self.current_price:.2f}")
        
        # Make a copy to avoid modification during iteration
        positions_to_check = list(self.open_positions)
        
        for position in positions_to_check:
            if position.status == "OPEN":
                if position.side == "LONG":
                    position.unrealized_pnl = (self.current_price - position.entry_price) * position.size
                else:  # SHORT
                    position.unrealized_pnl = (position.entry_price - self.current_price) * position.size
                
                # Check stop loss and take profit
                try:
                    self._check_exit_conditions(position)
                except Exception as e:
                    logger.error(f"Error checking exit conditions for {position.symbol} {position.side}: {e}", exc_info=True)
    
    def _check_exit_conditions(self, position: PaperPosition):
        """Check if position should be closed"""
        if position.status != "OPEN":
            return
        
        # Check time-based exit (4-hour max hold to prevent infinite positions)
        hold_duration = (datetime.now() - position.timestamp).total_seconds()
        max_hold_seconds = 4 * 3600  # 4 hours
        
        if hold_duration >= max_hold_seconds:
            logger.warning(f"⏰ TIME EXIT: Position held {hold_duration/3600:.1f}h (max {max_hold_seconds/3600}h)")
            self._close_position(position, self.current_price, "TIME_EXIT")
            return
        
        # Check stop loss with detailed logging
        if position.side == "LONG":
            if self.current_price <= position.stop_loss:
                logger.info(f"🛑 STOP LOSS HIT: {position.side} entry=${position.entry_price:.2f} sl=${position.stop_loss:.2f} current=${self.current_price:.2f}")
                self._close_position(position, self.current_price, "STOP_LOSS")
                return
        elif position.side == "SHORT":
            if self.current_price >= position.stop_loss:
                logger.info(f"🛑 STOP LOSS HIT: {position.side} entry=${position.entry_price:.2f} sl=${position.stop_loss:.2f} current=${self.current_price:.2f}")
                self._close_position(position, self.current_price, "STOP_LOSS")
                return
        
        # Check take profit with detailed logging
        if position.side == "LONG":
            if self.current_price >= position.take_profit:
                logger.info(f"🎯 TAKE PROFIT HIT: {position.side} entry=${position.entry_price:.2f} tp=${position.take_profit:.2f} current=${self.current_price:.2f}")
                self._close_position(position, self.current_price, "TAKE_PROFIT")
                return
        elif position.side == "SHORT":
            if self.current_price <= position.take_profit:
                logger.info(f"🎯 TAKE PROFIT HIT: {position.side} entry=${position.entry_price:.2f} tp=${position.take_profit:.2f} current=${self.current_price:.2f}")
                self._close_position(position, self.current_price, "TAKE_PROFIT")
                return
    
    def _emit_trade_summary(self, position: PaperPosition, trade: PaperTrade, 
                            exit_price: float, exit_reason: str):
        """Emit trade summary to ObservabilityHub for LLM analysis"""
        if not self.emitters:
            return
        
        try:
            # Calculate hold duration
            hold_duration_s = (trade.exit_time - trade.entry_time).total_seconds()
            
            # Calculate R-multiple (realized R vs risk)
            if position.risk_amount and position.risk_amount > 0:
                r_multiple = trade.pnl / position.risk_amount
            else:
                # Fallback: use SL distance as risk
                sl_distance = abs(position.entry_price - position.stop_loss)
                risk_estimate = sl_distance * position.size
                r_multiple = trade.pnl / risk_estimate if risk_estimate > 0 else 0.0
            
            # Convert cluster metrics to BPS if available
            edge_bps_at_entry = None  # TODO: Pass from decision context
            cluster_width_bps = None
            if position.cluster_width_pct:
                cluster_width_bps = position.cluster_width_pct * 10000  # % to BPS
            
            self.emitters.emit_trade_summary(
                decision_id=getattr(position, 'decision_id', None),
                side=position.side,
                entry_px=position.entry_price,
                exit_px=exit_price,
                qty=position.size,
                r_multiple=r_multiple,
                pnl_usd=trade.pnl,
                edge_bps_at_entry=edge_bps_at_entry,
                cluster_width_bps=cluster_width_bps,
                cluster_intensity_z=position.cluster_intensity_z,
                regime_tag=position.regime,
                exit_reason=exit_reason,
                hold_duration_s=hold_duration_s,
                veto_reasons=getattr(position, 'veto_reasons', None),
                guard_kinds=getattr(position, 'guard_kinds', None)
            )
        except Exception as e:
            logger.debug(f"Trade summary emission error: {e}")
    
    def _close_position(self, position: PaperPosition, exit_price: float, exit_reason: str):
        """Close a position and record the trade"""
        # Calculate P&L
        if position.side == "LONG":
            gross_pnl = (exit_price - position.entry_price) * position.size
        else:  # SHORT
            gross_pnl = (position.entry_price - exit_price) * position.size
        
        # Apply slippage and commission
        slippage_cost = abs(gross_pnl) * self.slippage_factor
        commission_cost = position.size * exit_price * self.commission_rate
        
        net_pnl = gross_pnl - slippage_cost - commission_cost
        pnl_percentage = net_pnl / (position.size * position.entry_price)
        
        # Create trade record
        trade = PaperTrade(
            symbol=position.symbol,
            side=position.side,
            size=position.size,
            entry_price=position.entry_price,
            exit_price=exit_price,
            entry_time=position.timestamp,
            exit_time=datetime.now(),
            pnl=net_pnl,
            pnl_percentage=pnl_percentage,
            exit_reason=exit_reason,
            confidence=position.confidence,
            risk_amount=position.risk_amount,
            entry_mode=position.entry_mode,
            signal_type=position.signal_type,
            regime=position.regime,
            multi_tf_score=position.multi_tf_score,
            cluster_width_pct=position.cluster_width_pct,
            cluster_intensity_z=position.cluster_intensity_z
        )
        
        # Update account
        self.balance += net_pnl
        self.total_pnl += net_pnl
        self.total_trades += 1
        
        if net_pnl > 0:
            self.winning_trades += 1
        
        # Update drawdown
        if self.balance > self.max_balance:
            self.max_balance = self.balance
        
        self.current_drawdown = (self.max_balance - self.balance) / self.max_balance
        if self.current_drawdown > self.max_drawdown:
            self.max_drawdown = self.current_drawdown
        
        # Remove from open positions and add to closed trades
        self.open_positions.remove(position)
        self.closed_trades.append(trade)
        
        # ===== TIER 1: WIRE RISK MANAGER PNL TRACKING =====
        # Inform risk manager about position closure for daily cap enforcement
        logger.info(f"🔍 DEBUG: risk_manager is {'None' if self.risk_manager is None else 'set'}")
        if self.risk_manager:
            try:
                # Convert PaperPosition to risk_management.Position for remove_position
                from risk_management import Position
                logger.info(f"📤 Calling risk_manager.remove_position for {position.symbol} {position.side} @ {position.entry_price}")
                risk_position = Position(
                    symbol=position.symbol,
                    side=position.side,
                    size=position.size,
                    entry_price=position.entry_price,
                    stop_loss=position.stop_loss,
                    take_profit=position.take_profit,
                    timestamp=position.timestamp,
                    confidence=position.confidence
                )
                # Call risk_manager.remove_position to update daily_pnl and current_positions
                self.risk_manager.remove_position(risk_position, exit_price, exit_reason)
                logger.info(f"✅ Risk manager updated with closed position: PnL=${net_pnl:.2f}")
            except Exception as e:
                logger.error(f"❌ Failed to update risk manager on position close: {e}", exc_info=True)
        else:
            logger.warning(f"⚠️ risk_manager is None, cannot remove position from tracking!")
        
        # Emit trade summary for LLM/observability
        self._emit_trade_summary(position, trade, exit_price, exit_reason)
        
        # ===== CRITICAL: Notify signal_generator for exit fill logging =====
        # This ensures fill.jsonl gets exit events with proper exit_type, hold_duration, r_multiple
        if self.exit_callback:
            try:
                hold_duration_s = (trade.exit_time - trade.entry_time).total_seconds()
                r_multiple = net_pnl / position.risk_amount if position.risk_amount > 0 else 0.0
                
                self.exit_callback(
                    position=position,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    pnl=net_pnl,
                    hold_duration_s=hold_duration_s,
                    r_multiple=r_multiple
                )
                logger.info(f"✅ Exit callback notified: {exit_reason} pnl=${net_pnl:.2f} r={r_multiple:.2f}")
            except Exception as e:
                logger.error(f"Exit callback failed: {e}", exc_info=True)
        
        logger.info(f"Position closed: {position.side} {position.size:.6f} BTC "
                   f"Entry: ${position.entry_price:.2f} Exit: ${exit_price:.2f} "
                   f"P&L: ${net_pnl:.2f} ({pnl_percentage:.2%}) Reason: {exit_reason}")
    
    def open_position(self, symbol: str, side: str, size: float, entry_price: float,
                     stop_loss: float, take_profit: float, confidence: float,
                     **metadata) -> bool:
        """Open a new position"""
        try:
            # Calculate position value
            position_value = size * entry_price
            
            # Check if we have enough balance
            if position_value > self.balance * 0.95:  # Leave 5% buffer
                logger.warning(f"Insufficient balance for position: ${position_value:.2f} > ${self.balance * 0.95:.2f}")
                return False
            
            # Apply slippage to entry price
            slippage = entry_price * self.slippage_factor
            if side == "LONG":
                actual_entry_price = entry_price + slippage
            else:
                actual_entry_price = entry_price - slippage
            
            # Calculate commission
            commission = size * actual_entry_price * self.commission_rate
            
            # Create position
            position = PaperPosition(
                symbol=symbol,
                side=side,
                size=size,
                entry_price=actual_entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                timestamp=datetime.now(),
                confidence=confidence,
                risk_amount=abs(actual_entry_price - stop_loss) * size,
                entry_mode=metadata.get('entry_mode'),
                signal_type=metadata.get('signal_type'),
                regime=metadata.get('regime'),
                multi_tf_score=metadata.get('multi_tf_score'),
                cluster_width_pct=metadata.get('cluster_width_pct'),
                cluster_intensity_z=metadata.get('cluster_intensity_z')
            )
            
            # Deduct commission from balance
            self.balance -= commission
            
            # Add position
            self.open_positions.append(position)
            
            logger.info(f"✅ PAPER BRACKET REGISTERED: {side} {size:.6f} BTC at ${actual_entry_price:.2f} "
                       f"SL=${stop_loss:.2f} TP=${take_profit:.2f} (Commission: ${commission:.2f})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error opening position: {e}")
            return False
    
    def get_account_summary(self) -> Dict:
        """Get account summary"""
        total_position_value = sum(pos.size * self.current_price for pos in self.open_positions)
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self.open_positions)
        
        win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
        
        return {
            'balance': self.balance,
            'initial_balance': self.initial_balance,
            'total_pnl': self.total_pnl,
            'total_pnl_percentage': (self.balance - self.initial_balance) / self.initial_balance,
            'unrealized_pnl': total_unrealized_pnl,
            'total_position_value': total_position_value,
            'open_positions': len(self.open_positions),
            'total_trades': self.total_trades,
            'winning_trades': self.winning_trades,
            'win_rate': win_rate,
            'max_drawdown': self.max_drawdown,
            'current_drawdown': self.current_drawdown,
            'current_price': self.current_price
        }
    
    def get_performance_metrics(self) -> Dict:
        """Get detailed performance metrics"""
        if len(self.closed_trades) < 2:
            return {'error': 'Insufficient trade data'}
        
        # Calculate returns
        returns = [trade.pnl_percentage for trade in self.closed_trades]
        returns_series = pd.Series(returns)
        
        # Basic metrics
        total_return = (self.balance - self.initial_balance) / self.initial_balance
        avg_return = returns_series.mean()
        volatility = returns_series.std() * np.sqrt(252)  # Annualized
        
        # Risk metrics
        sharpe_ratio = avg_return / returns_series.std() * np.sqrt(252) if returns_series.std() > 0 else 0
        
        # Drawdown analysis
        cumulative_returns = (1 + returns_series).cumprod()
        running_max = cumulative_returns.expanding().max()
        drawdowns = (cumulative_returns - running_max) / running_max
        max_drawdown = abs(drawdowns.min())
        
        # Win/Loss analysis
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]
        
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses else float('inf')
        
        return {
            'total_return': total_return,
            'annualized_return': avg_return * 252,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': len(wins) / len(returns),
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_trades': len(self.closed_trades),
            'winning_trades': len(wins),
            'losing_trades': len(losses)
        }
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get recent trades"""
        recent_trades = self.closed_trades[-limit:] if self.closed_trades else []
        
        return [
            {
                'symbol': trade.symbol,
                'side': trade.side,
                'size': trade.size,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'entry_time': trade.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'exit_time': trade.exit_time.strftime('%Y-%m-%d %H:%M:%S'),
                'pnl': trade.pnl,
                'pnl_percentage': trade.pnl_percentage,
                'exit_reason': trade.exit_reason,
                'confidence': trade.confidence
            }
            for trade in recent_trades
        ]
    
    def reset_account(self):
        """Reset account to initial state"""
        self.balance = self.initial_balance
        self.max_balance = self.initial_balance
        self.open_positions.clear()
        self.closed_trades.clear()
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        
        logger.info("Account reset to initial state")
    
    def set_current_price(self, price: float):
        """Set current price from WebSocket feed"""
        self.current_price = price
        self.price_history.append({
            'timestamp': datetime.now(),
            'price': self.current_price
        })
        self._update_open_positions()
    
    def get_current_price(self) -> float:
        """Get current simulated price"""
        return self.current_price

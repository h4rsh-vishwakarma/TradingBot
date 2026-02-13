"""
PositionReconciler - Detect Drift Between Virtual and Testnet Balances

Monitors:
- Virtual balance (our calculation)
- Testnet balance (Binance actual)
- Balance drift (difference between them)

Alerts when drift exceeds thresholds:
- WARNING: > 1% drift
- CRITICAL: > 5% drift

Causes of drift:
- Calculation errors in P&L tracking
- Missed order fills/cancellations
- Exchange fees not accounted for
- Funding fees (futures contracts)
- Manual interventions on exchange
"""

import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
import logging

from exchange.binance_client import BinanceClient
from utils.event_logger import get_event_logger

logger = logging.getLogger(__name__)


class PositionReconciler:
    """
    Reconciles virtual balance against testnet balance to detect drift.
    
    Drift detection helps identify:
    - P&L calculation bugs
    - Missed order events
    - Exchange fee discrepancies
    - Manual interventions
    """
    
    # Drift thresholds
    WARNING_THRESHOLD = 0.01  # 1% drift triggers warning
    CRITICAL_THRESHOLD = 0.05  # 5% drift triggers critical alert
    
    def __init__(self, client: BinanceClient, 
                 check_interval: int = 300):  # 5 minutes
        """
        Initialize reconciler.
        
        Args:
            client: Binance client for balance queries
            check_interval: Seconds between reconciliation checks
        """
        self.client = client
        self.check_interval = check_interval
        self.event_logger = get_event_logger()
        
        # Track reconciliation history
        self.last_check = None
        self.drift_history = []
        self.max_drift_seen = 0.0
        
        logger.info(f"🔍 PositionReconciler initialized (check every {check_interval}s)")
    
    def calculate_drift(self, virtual_balance: float, 
                       testnet_balance: float) -> Tuple[float, float]:
        """
        Calculate absolute and percentage drift.
        
        Args:
            virtual_balance: Our calculated balance
            testnet_balance: Binance testnet balance
            
        Returns:
            Tuple of (absolute_drift, drift_percentage)
        """
        absolute_drift = abs(virtual_balance - testnet_balance)
        
        # Avoid division by zero
        if testnet_balance == 0:
            drift_pct = 1.0 if virtual_balance != 0 else 0.0
        else:
            drift_pct = absolute_drift / testnet_balance
        
        return absolute_drift, drift_pct
    
    def check_balance_drift(self, virtual_balance: float) -> Dict:
        """
        Check for balance drift between virtual and testnet.
        
        Args:
            virtual_balance: Our calculated balance
            
        Returns:
            Dictionary with reconciliation results
        """
        try:
            # Get testnet balance from Binance
            testnet_balance = self.client.get_balance('USDT')
            
            # Calculate drift
            absolute_drift, drift_pct = self.calculate_drift(
                virtual_balance, testnet_balance
            )
            
            # Determine severity
            threshold_exceeded = drift_pct > self.WARNING_THRESHOLD
            is_critical = drift_pct > self.CRITICAL_THRESHOLD
            
            # Update tracking
            self.last_check = datetime.now(timezone.utc)
            self.drift_history.append({
                'timestamp': self.last_check.isoformat(),
                'drift_pct': drift_pct,
                'absolute_drift': absolute_drift
            })
            
            # Keep only last 100 checks
            if len(self.drift_history) > 100:
                self.drift_history = self.drift_history[-100:]
            
            # Track max drift
            if drift_pct > self.max_drift_seen:
                self.max_drift_seen = drift_pct
            
            # Log to event system
            self.event_logger.log_reconciliation(
                virtual_balance=virtual_balance,
                testnet_balance=testnet_balance,
                drift=absolute_drift,
                drift_pct=drift_pct,
                threshold_exceeded=threshold_exceeded
            )
            
            # Log severity-based messages
            if is_critical:
                logger.critical(
                    f"🚨 CRITICAL DRIFT DETECTED!\n"
                    f"   Virtual: ${virtual_balance:.2f}\n"
                    f"   Testnet: ${testnet_balance:.2f}\n"
                    f"   Drift: ${absolute_drift:.2f} ({drift_pct:.2%})\n"
                    f"   Threshold: {self.CRITICAL_THRESHOLD:.1%}"
                )
            elif threshold_exceeded:
                logger.warning(
                    f"⚠️ Balance drift detected\n"
                    f"   Virtual: ${virtual_balance:.2f}\n"
                    f"   Testnet: ${testnet_balance:.2f}\n"
                    f"   Drift: ${absolute_drift:.2f} ({drift_pct:.2%})\n"
                    f"   Threshold: {self.WARNING_THRESHOLD:.1%}"
                )
            else:
                logger.info(
                    f"✅ Balance reconciliation OK\n"
                    f"   Virtual: ${virtual_balance:.2f}\n"
                    f"   Testnet: ${testnet_balance:.2f}\n"
                    f"   Drift: ${absolute_drift:.2f} ({drift_pct:.2%})"
                )
            
            return {
                'timestamp': self.last_check.isoformat(),
                'virtual_balance': virtual_balance,
                'testnet_balance': testnet_balance,
                'absolute_drift': absolute_drift,
                'drift_pct': drift_pct,
                'threshold_exceeded': threshold_exceeded,
                'is_critical': is_critical,
                'status': 'critical' if is_critical else ('warning' if threshold_exceeded else 'ok')
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to reconcile balances: {e}")
            self.event_logger.log_critical_failure(
                component='PositionReconciler',
                error=str(e),
                context={'virtual_balance': virtual_balance}
            )
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def should_check(self) -> bool:
        """
        Determine if it's time for reconciliation check.
        
        Returns:
            True if check interval has elapsed
        """
        if self.last_check is None:
            return True
        
        elapsed = (datetime.now(timezone.utc) - self.last_check).total_seconds()
        return elapsed >= self.check_interval
    
    def get_drift_stats(self) -> Dict:
        """
        Get drift statistics from history.
        
        Returns:
            Dictionary with drift statistics
        """
        if not self.drift_history:
            return {
                'checks_performed': 0,
                'avg_drift_pct': 0.0,
                'max_drift_pct': 0.0,
                'last_check': None
            }
        
        avg_drift = sum(entry['drift_pct'] for entry in self.drift_history) / len(self.drift_history)
        
        return {
            'checks_performed': len(self.drift_history),
            'avg_drift_pct': avg_drift,
            'max_drift_pct': self.max_drift_seen,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'recent_drifts': self.drift_history[-10:]  # Last 10 checks
        }
    
    def force_reconciliation(self, virtual_balance: float) -> Dict:
        """
        Force immediate reconciliation check (bypass interval).
        
        Args:
            virtual_balance: Our calculated balance
            
        Returns:
            Reconciliation results
        """
        logger.info("🔍 Forcing balance reconciliation...")
        return self.check_balance_drift(virtual_balance)

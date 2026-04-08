"""
Virtual Balance Manager
Tracks virtual balance per strategy with file locking for safety
"""

import json
import fcntl
import os
import time
from threading import Lock
from utils.logger import setup_logger

logger = setup_logger('balance_manager')

class BalanceManager:
    """Manages virtual balance for a single strategy bot"""
    
    def __init__(self, balance_file, initial_balance=100.0):
        """
        Initialize balance manager
        
        Args:
            balance_file: Path to balance JSON file
            initial_balance: Starting balance if file doesn't exist
        """
        self.balance_file = balance_file
        self.initial_balance = initial_balance
        self.lock = Lock()
        
        # Create balance file if it doesn't exist
        if not os.path.exists(balance_file):
            self._create_balance_file()
        
        logger.info(f"💰 Balance Manager initialized: {balance_file}")
    
    def _create_balance_file(self):
        """Create initial balance file"""
        os.makedirs(os.path.dirname(self.balance_file), exist_ok=True)
        
        balance_data = {
            "balance": self.initial_balance,
            "initial": self.initial_balance,
            "realized_pnl": 0.0,
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "last_updated": time.time()
        }
        
        with open(self.balance_file, 'w') as f:
            json.dump(balance_data, f, indent=2)
        
        logger.info(f"✅ Created balance file with ${self.initial_balance:.2f}")
    
    def get_balance(self):
        """Get current virtual balance"""
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    data = json.load(f)
                return data.get('balance', self.initial_balance)
            except Exception as e:
                logger.error(f"❌ Error reading balance: {e}")
                return self.initial_balance
    
    def get_performance_summary(self):
        """Get performance statistics"""
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    data = json.load(f)
                
                total_trades = data.get('total_trades', 0)
                winning_trades = data.get('winning_trades', 0)
                losing_trades = data.get('losing_trades', 0)
                realized_pnl = data.get('realized_pnl', 0.0)
                current_balance = data.get('balance', self.initial_balance)
                initial_balance = data.get('initial', self.initial_balance)
                
                win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
                roi_percent = ((current_balance - initial_balance) / initial_balance * 100) if initial_balance > 0 else 0
                
                return {
                    'current_balance': current_balance,
                    'initial_balance': initial_balance,
                    'realized_pnl': realized_pnl,
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'losing_trades': losing_trades,
                    'win_rate_percent': win_rate,
                    'roi_percent': roi_percent
                }
                
            except Exception as e:
                logger.error(f"❌ Error getting performance summary: {e}")
                return {
                    'current_balance': self.initial_balance,
                    'initial_balance': self.initial_balance,
                    'realized_pnl': 0.0,
                    'total_trades': 0,
                    'winning_trades': 0,
                    'losing_trades': 0,
                    'win_rate_percent': 0.0,
                    'roi_percent': 0.0
                }
    
    def get_full_stats(self):
        """Get all balance statistics (for backward compatibility)"""
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"❌ Error reading balance stats: {e}")
                return {
                    "balance": self.initial_balance,
                    "initial": self.initial_balance,
                    "realized_pnl": 0.0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0
                }
    
    def reserve_balance(self, amount):
        """
        Reserve balance for a trade (deduct from available)
        
        Args:
            amount: Amount to reserve
            
        Returns:
            bool: True if successful, False if insufficient balance
        """
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    data = json.load(f)
                
                current_balance = data.get('balance', self.initial_balance)
                
                if current_balance < amount:
                    logger.warning(f"⚠️ Insufficient virtual balance: ${current_balance:.2f} < ${amount:.2f}")
                    return False
                
                # Deduct amount
                data['balance'] = current_balance - amount
                data['last_updated'] = time.time()
                
                with open(self.balance_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                logger.info(f"💸 Reserved ${amount:.2f} | Remaining: ${data['balance']:.2f}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Error reserving balance: {e}")
                return False
    
    def release_balance(self, amount):
        """
        Release reserved balance back (add to available)
        Used when order fails or is cancelled
        
        Args:
            amount: Amount to release
        """
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    data = json.load(f)
                
                data['balance'] = data.get('balance', self.initial_balance) + amount
                data['last_updated'] = time.time()
                
                with open(self.balance_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                logger.info(f"💰 Released ${amount:.2f} | New balance: ${data['balance']:.2f}")
                
            except Exception as e:
                logger.error(f"❌ Error releasing balance: {e}")
    
    def update_on_close(self, position_size, realized_pnl):
        """
        Update balance when position closes
        
        Args:
            position_size: Original position size
            realized_pnl: Profit or loss from the trade
        """
        with self.lock:
            try:
                with open(self.balance_file, 'r') as f:
                    data = json.load(f)
                
                # Return position size + PnL (capital was deducted on reserve)
                data['balance'] = data.get('balance', self.initial_balance) + position_size + realized_pnl
                data['realized_pnl'] = data.get('realized_pnl', 0.0) + realized_pnl
                data['total_trades'] = data.get('total_trades', 0) + 1
                
                if realized_pnl > 0:
                    data['winning_trades'] = data.get('winning_trades', 0) + 1
                elif realized_pnl < 0:
                    data['losing_trades'] = data.get('losing_trades', 0) + 1
                
                data['last_updated'] = time.time()
                
                with open(self.balance_file, 'w') as f:
                    json.dump(data, f, indent=2)
                
                win_rate = (data['winning_trades'] / data['total_trades'] * 100) if data['total_trades'] > 0 else 0
                
                logger.info(f"📊 Position closed | PnL: ${realized_pnl:+.2f} | Balance: ${data['balance']:.2f} | "
                           f"Total PnL: ${data['realized_pnl']:+.2f} | Win Rate: {win_rate:.1f}%")
                
            except Exception as e:
                logger.error(f"❌ Error updating balance on close: {e}")
    
    def reset_balance(self, new_balance=None):
        """
        Reset balance to initial or specified amount
        
        Args:
            new_balance: New balance amount (uses initial if None)
        """
        with self.lock:
            try:
                reset_amount = new_balance if new_balance is not None else self.initial_balance
                
                balance_data = {
                    "balance": reset_amount,
                    "initial": reset_amount,
                    "realized_pnl": 0.0,
                    "total_trades": 0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "last_updated": time.time()
                }
                
                with open(self.balance_file, 'w') as f:
                    json.dump(balance_data, f, indent=2)
                
                logger.info(f"🔄 Balance reset to ${reset_amount:.2f}")
                
            except Exception as e:
                logger.error(f"❌ Error resetting balance: {e}")
    
    def get_performance_summary(self):
        """Get formatted performance summary"""
        stats = self.get_full_stats()
        
        current = stats.get('balance', 0)
        initial = stats.get('initial', 0)
        pnl = stats.get('realized_pnl', 0)
        total = stats.get('total_trades', 0)
        wins = stats.get('winning_trades', 0)
        losses = stats.get('losing_trades', 0)
        
        win_rate = (wins / total * 100) if total > 0 else 0
        roi = ((current - initial) / initial * 100) if initial > 0 else 0
        
        return {
            'current_balance': current,
            'initial_balance': initial,
            'realized_pnl': pnl,
            'roi_percent': roi,
            'total_trades': total,
            'winning_trades': wins,
            'losing_trades': losses,
            'win_rate_percent': win_rate
        }

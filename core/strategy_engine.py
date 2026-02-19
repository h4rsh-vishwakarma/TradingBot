"""
Strategy Engine - Uses ONLY mainnet prices for all decisions
STRICT RULE: This module NEVER uses testnet price data
"""

from exchange.price_provider import get_price_provider
from utils.logger import setup_logger
import time

logger = setup_logger('strategy_engine')

class StrategyEngine:
    """
    Strategy engine that uses ONLY mainnet prices
    All entry, exit, and P&L calculations use real market prices
    """
    
    def __init__(self, config):
        self.config = config
        self.price_provider = get_price_provider()
        
        logger.info("🧠 Strategy engine initialized - MAINNET PRICES ONLY")
    
    def validate_signal_entry(self, signal):
        """
        Validate signal entry using MAINNET price
        Returns optimal entry price and validation result
        """
        try:
            symbol = signal['symbol']
            side = signal['side']
            signal_price = float(signal.get('price', 0))
            
            # Get MAINNET price for validation
            mainnet_price = self.price_provider.get_current_price(symbol)
            
            if mainnet_price == 0:
                logger.error(f"❌ [STRATEGY] Could not get mainnet price for {symbol}")
                return None, False
            
            # Calculate price deviation
            if signal_price > 0:
                deviation_pct = abs(mainnet_price - signal_price) / signal_price * 100
                if deviation_pct > 5.0:  # 5% max deviation
                    logger.warning(f"⚠️ [STRATEGY] Signal price deviation too high: {deviation_pct:.2f}%")
            
            # Get optimal entry price based on mainnet orderbook
            optimal_entry_price = self.price_provider.get_optimal_limit_price(
                symbol, side, aggressive=True  # Use market price for entry
            )
            
            logger.info(f"✅ [STRATEGY] Entry validated: {symbol} {side} @ ${optimal_entry_price:.2f} (mainnet: ${mainnet_price:.2f})")
            
            return optimal_entry_price, True
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to validate signal entry: {e}")
            return None, False
    
    def calculate_stop_loss_price(self, signal, entry_price):
        """
        Calculate stop-loss price using MAINNET price as reference
        """
        try:
            side = signal['side']
            stop_loss = float(signal.get('stop_loss', 0))
            
            if stop_loss == 0:
                logger.warning(f"⚠️ [STRATEGY] No stop-loss provided in signal")
                return None
            
            # Validate SL direction
            if side.upper() == 'LONG' and stop_loss >= entry_price:
                logger.error(f"❌ [STRATEGY] Invalid LONG SL: ${stop_loss:.2f} >= entry ${entry_price:.2f}")
                return None
            elif side.upper() == 'SHORT' and stop_loss <= entry_price:
                logger.error(f"❌ [STRATEGY] Invalid SHORT SL: ${stop_loss:.2f} <= entry ${entry_price:.2f}")
                return None
            
            # Get optimal SL price (slightly less aggressive than entry)
            sl_side = 'SELL' if side.upper() == 'LONG' else 'BUY'
            optimal_sl_price = self.price_provider.get_optimal_limit_price(
                signal['symbol'], sl_side, aggressive=False
            )
            
            # Use signal SL if it's more conservative than optimal
            if side.upper() == 'LONG':
                final_sl = min(stop_loss, optimal_sl_price) if optimal_sl_price > 0 else stop_loss
            else:
                final_sl = max(stop_loss, optimal_sl_price) if optimal_sl_price > 0 else stop_loss
            
            logger.info(f"🛑 [STRATEGY] SL calculated: ${final_sl:.2f} (signal: ${stop_loss:.2f})")
            return final_sl
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to calculate SL price: {e}")
            return None
    
    def calculate_take_profit_price(self, signal, entry_price):
        """
        Calculate take-profit price using MAINNET price as reference
        """
        try:
            side = signal['side']
            take_profit = float(signal.get('take_profit', 0))
            
            if take_profit == 0:
                logger.warning(f"⚠️ [STRATEGY] No take-profit provided in signal")
                return None
            
            # Validate TP direction
            if side.upper() == 'LONG' and take_profit <= entry_price:
                logger.error(f"❌ [STRATEGY] Invalid LONG TP: ${take_profit:.2f} <= entry ${entry_price:.2f}")
                return None
            elif side.upper() == 'SHORT' and take_profit >= entry_price:
                logger.error(f"❌ [STRATEGY] Invalid SHORT TP: ${take_profit:.2f} >= entry ${entry_price:.2f}")
                return None
            
            # Get optimal TP price
            tp_side = 'SELL' if side.upper() == 'LONG' else 'BUY'
            optimal_tp_price = self.price_provider.get_optimal_limit_price(
                signal['symbol'], tp_side, aggressive=False
            )
            
            # Use signal TP if it's more conservative than optimal
            if side.upper() == 'LONG':
                final_tp = max(take_profit, optimal_tp_price) if optimal_tp_price > 0 else take_profit
            else:
                final_tp = min(take_profit, optimal_tp_price) if optimal_tp_price > 0 else take_profit
            
            logger.info(f"🎯 [STRATEGY] TP calculated: ${final_tp:.2f} (signal: ${take_profit:.2f})")
            return final_tp
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to calculate TP price: {e}")
            return None
    
    def should_close_position(self, position, current_mainnet_price=None):
        """
        Determine if position should be closed based on MAINNET price
        """
        try:
            symbol = position['symbol']
            side = position['side']
            entry_price = float(position['entry_price'])
            
            # Get current MAINNET price
            if current_mainnet_price is None:
                current_mainnet_price = self.price_provider.get_current_price(symbol)
            
            if current_mainnet_price == 0:
                logger.error(f"❌ [STRATEGY] Could not get mainnet price for position check: {symbol}")
                return False, None
            
            # Check stop-loss
            stop_loss = float(position.get('stop_loss', 0))
            if stop_loss > 0:
                if side.upper() == 'LONG' and current_mainnet_price <= stop_loss:
                    logger.info(f"🛑 [STRATEGY] LONG SL triggered: ${current_mainnet_price:.2f} <= ${stop_loss:.2f}")
                    return True, 'STOP_LOSS'
                elif side.upper() == 'SHORT' and current_mainnet_price >= stop_loss:
                    logger.info(f"🛑 [STRATEGY] SHORT SL triggered: ${current_mainnet_price:.2f} >= ${stop_loss:.2f}")
                    return True, 'STOP_LOSS'
            
            # Check take-profit
            take_profit = float(position.get('take_profit', 0))
            if take_profit > 0:
                if side.upper() == 'LONG' and current_mainnet_price >= take_profit:
                    logger.info(f"🎯 [STRATEGY] LONG TP triggered: ${current_mainnet_price:.2f} >= ${take_profit:.2f}")
                    return True, 'TAKE_PROFIT'
                elif side.upper() == 'SHORT' and current_mainnet_price <= take_profit:
                    logger.info(f"🎯 [STRATEGY] SHORT TP triggered: ${current_mainnet_price:.2f} <= ${take_profit:.2f}")
                    return True, 'TAKE_PROFIT'
            
            return False, None
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to check position close conditions: {e}")
            return False, None
    
    def calculate_position_pnl(self, position, exit_price=None):
        """
        Calculate position P&L using MAINNET prices ONLY
        """
        try:
            symbol = position['symbol']
            side = position['side']
            entry_price = float(position['entry_price'])
            quantity = float(position['position_size'])
            
            # Use provided exit price or get current MAINNET price
            if exit_price is None:
                exit_price = self.price_provider.get_current_price(symbol)
            
            if exit_price == 0:
                logger.error(f"❌ [STRATEGY] Could not get exit price for P&L calculation: {symbol}")
                return 0.0
            
            # Calculate P&L using MAINNET prices
            pnl = self.price_provider.calculate_pnl(side, entry_price, exit_price, quantity)
            
            logger.info(f"💰 [STRATEGY] P&L calculated: {side} {quantity} @ ${entry_price:.2f} -> ${exit_price:.2f} = ${pnl:.4f}")
            return pnl
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to calculate P&L: {e}")
            return 0.0
    
    def get_market_info(self, symbol):
        """Get comprehensive market information from MAINNET"""
        try:
            price_info = self.price_provider.get_price_info(symbol)
            
            if price_info:
                logger.debug(f"📊 [STRATEGY] Market info: {symbol} @ ${price_info['price']:.2f}, spread: {price_info['spread_pct']:.3f}%")
            
            return price_info
            
        except Exception as e:
            logger.error(f"❌ [STRATEGY] Failed to get market info for {symbol}: {e}")
            return None
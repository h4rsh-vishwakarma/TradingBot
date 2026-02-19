from utils.logger import setup_logger
from utils.helpers import calculate_position_size

logger = setup_logger('risk_manager')

class RiskManager:
    """Manage trading risk and position sizing"""
    
    def __init__(self, config):
        self.config = config
        self.position_size_type = config['risk']['position_size_type']
        self.position_size_value = config['risk']['position_size_value']
        self.max_symbol_exposure = config['risk']['max_symbol_exposure']
        self.min_position_usd = config['risk']['min_position_usd']
        self.leverage = config['trading']['leverage']
        
        logger.info(f"🛡️ Risk manager initialized")
        logger.info(f"   Position sizing: {self.position_size_value}% of balance")
        logger.info(f"   Leverage: {self.leverage}x")
        logger.info(f"   Max symbol exposure: {self.max_symbol_exposure}%")
    
    def calculate_position_size(self, balance, price):
        """Calculate position size in contracts/coins"""
        try:
            # Calculate USD size
            usd_size = calculate_position_size(
                balance, 
                self.position_size_type, 
                self.position_size_value,
                self.leverage
            )
            
            # Binance Futures minimum notional is $100 for BTCUSDT
            binance_min_notional = 50
            
            # Use larger of configured minimum or Binance minimum
            min_required = max(self.min_position_usd, binance_min_notional)
            
            if usd_size < min_required:
                logger.warning(f"[WARN] Position size ${usd_size:.2f} below minimum ${min_required}, using minimum")
                usd_size = min_required
            
            # Convert to contracts (amount of coins)
            contracts = usd_size / float(price)
            
            # Round to 3 decimals (Binance BTCUSDT quantity precision)
            contracts = round(contracts, 3)
            
            # Verify final notional is still >= minimum
            final_notional = contracts * price
            if final_notional < binance_min_notional:
                # Add one more step to ensure we're above minimum
                contracts = round((binance_min_notional * 1.05) / price, 3)
                final_notional = contracts * price
                
                # Double-check after adjustment - if still below minimum, reject
                if final_notional < binance_min_notional:
                    logger.error(f"❌ Cannot meet minimum notional: ${final_notional:.2f} < ${binance_min_notional}. Insufficient balance.")
                    return 0.0
            
            logger.info(f"[POSITION] Size: ${final_notional:.2f} = {contracts:.3f} contracts @ ${price:.2f}")
            
            return contracts
        except Exception as e:
            logger.error(f"Failed to calculate position size: {e}")
            return 0.0
    
    def check_symbol_exposure(self, symbol, new_position_usd, current_exposure_usd, balance):
        """Check if new position would exceed symbol exposure limit"""
        try:
            total_exposure = current_exposure_usd + new_position_usd
            exposure_pct = (total_exposure / balance) * 100
            
            if exposure_pct > self.max_symbol_exposure:
                logger.warning(
                    f"⚠️ Symbol exposure limit: {symbol} would be {exposure_pct:.1f}% "
                    f"(max: {self.max_symbol_exposure}%)"
                )
                return False
            
            logger.info(f"✅ Symbol exposure OK: {symbol} = {exposure_pct:.1f}% (max: {self.max_symbol_exposure}%)")
            return True
        except Exception as e:
            logger.error(f"Failed to check symbol exposure: {e}")
            return False
    
    def validate_sl_tp(self, side, entry_price, stop_loss, take_profit):
        """Validate stop-loss and take-profit levels"""
        try:
            entry = float(entry_price)
            sl = float(stop_loss)
            tp = float(take_profit)
            
            # Initialize rr_ratio
            rr_ratio = 0.0
            
            if side == 'LONG':
                # SL should be below entry
                if sl >= entry:
                    logger.error(f"❌ LONG: Stop-loss ${sl:.2f} must be < entry ${entry:.2f}")
                    return False
                
                # TP should be above entry
                if tp <= entry:
                    logger.error(f"❌ LONG: Take-profit ${tp:.2f} must be > entry ${entry:.2f}")
                    return False
                
                # Calculate R:R
                risk = entry - sl
                reward = tp - entry
                rr_ratio = reward / risk if risk > 0 else 0
                
            elif side == 'SHORT':
                # SL should be above entry
                if sl <= entry:
                    logger.error(f"❌ SHORT: Stop-loss ${sl:.2f} must be > entry ${entry:.2f}")
                    return False
                
                # TP should be below entry
                if tp >= entry:
                    logger.error(f"❌ SHORT: Take-profit ${tp:.2f} must be < entry ${entry:.2f}")
                    return False
                
                # Calculate R:R
                risk = sl - entry
                reward = entry - tp
                rr_ratio = reward / risk if risk > 0 else 0
            else:
                logger.error(f"❌ Invalid side: {side} (must be LONG or SHORT)")
                return False
            
            logger.info(f"✅ SL/TP valid | Risk:Reward = 1:{rr_ratio:.2f}")
            return True
            
        except (ValueError, TypeError) as e:
            logger.error(f"❌ Failed to validate SL/TP: {e}")
            return False
    
    def apply_sl_buffer(self, side, stop_loss, timeframe=None):
        """Apply buffer to stop-loss with timeframe-based adjustments"""
        try:
            sl = float(stop_loss)
            
            # Base buffer percentage
            base_buffer_pct = self.config['risk'].get('stop_loss_buffer_pct', 0.1)
            
            # Timeframe-based buffer adjustments
            timeframe_buffers = {
                '1m': 0.3,   # 0.3% for 1-minute (very volatile)
                '2m': 0.25,  # 0.25% for 2-minute (volatile)
                '5m': 0.2,   # 0.2% for 5-minute
                '15m': 0.15, # 0.15% for 15-minute
                '30m': 0.1,  # 0.1% for 30-minute
                '1h': 0.05,  # 0.05% for 1-hour (less volatile)
                '4h': 0.05,  # 0.05% for 4-hour
                '1d': 0.05   # 0.05% for daily
            }
            
            # Get timeframe-specific buffer
            if timeframe and timeframe in timeframe_buffers:
                buffer_pct = timeframe_buffers[timeframe]
                logger.info(f"📊 Using {timeframe} buffer: {buffer_pct}% (base: {base_buffer_pct}%)")
            else:
                buffer_pct = base_buffer_pct
                logger.info(f"📊 Using default buffer: {buffer_pct}%")
            
            if side == 'LONG':
                # Move SL slightly lower (more conservative)
                adjusted_sl = sl * (1 - buffer_pct / 100)
            else:  # SHORT
                # Move SL slightly higher (more conservative)
                adjusted_sl = sl * (1 + buffer_pct / 100)
            
            logger.info(f"🛡️ SL buffer applied: ${sl:.2f} → ${adjusted_sl:.2f} (buffer: {buffer_pct}%)")
            return adjusted_sl
        except Exception as e:
            logger.warning(f"Failed to apply SL buffer: {e}")
            return float(stop_loss)
    
    def validate_minimum_sl_distance(self, side, entry_price, stop_loss, timeframe=None):
        """Validate minimum stop-loss distance based on timeframe volatility"""
        try:
            entry = float(entry_price)
            sl = float(stop_loss)
            
            # Minimum SL distance as percentage of entry price
            min_distances = {
                '1m': 0.5,   # 0.5% minimum for 1-minute
                '2m': 0.4,   # 0.4% minimum for 2-minute
                '5m': 0.3,   # 0.3% minimum for 5-minute
                '15m': 0.2,  # 0.2% minimum for 15-minute
                '30m': 0.15, # 0.15% minimum for 30-minute
                '1h': 0.1,   # 0.1% minimum for 1-hour
                '4h': 0.1,   # 0.1% minimum for 4-hour
                '1d': 0.1    # 0.1% minimum for daily
            }
            
            # Get minimum distance for timeframe
            min_distance_pct = min_distances.get(timeframe, 0.2)  # Default 0.2%
            
            # Calculate actual distance
            if side == 'LONG':
                actual_distance_pct = ((entry - sl) / entry) * 100
            else:  # SHORT
                actual_distance_pct = ((sl - entry) / entry) * 100
            
            if actual_distance_pct < min_distance_pct:
                logger.warning(
                    f"⚠️ SL too tight for {timeframe}: {actual_distance_pct:.2f}% < {min_distance_pct:.2f}% minimum"
                )
                
                # Suggest better SL
                if side == 'LONG':
                    suggested_sl = entry * (1 - min_distance_pct / 100)
                else:
                    suggested_sl = entry * (1 + min_distance_pct / 100)
                
                logger.info(f"💡 Suggested SL for {timeframe}: ${suggested_sl:.2f}")
                return False, suggested_sl
            
            logger.info(f"✅ SL distance OK for {timeframe}: {actual_distance_pct:.2f}% >= {min_distance_pct:.2f}%")
            return True, sl
            
        except Exception as e:
            logger.error(f"Failed to validate SL distance: {e}")
            return True, float(stop_loss)  # Allow on error

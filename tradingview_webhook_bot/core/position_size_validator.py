"""
Position Size Validator - Prevents catastrophic sizing errors
"""
from utils.logger import setup_logger

logger = setup_logger('position_size_validator')

class PositionSizeValidator:
    """
    SECURITY LAYER: Validates all position sizes BEFORE order execution.
    
    CRITICAL PROTECTION AGAINST:
    - Malicious or malformed webhook data
    - Bug in position size calculation
    - Misconfigured TradingView alerts
    - Accidental 1000x oversized positions
    
    Rules:
    1. Never trust position_size from external webhooks
    2. Always recalculate based on risk management rules  
    3. Apply hard caps: max notional, max contracts
    4. Log and alert on anomalies
    5. Use multi-layer validation before any trade
    """
    
    def __init__(self, config):
        self.config = config
        # Allow 50% over calculated size as safety buffer (handles minor price movements)
        self.max_notional_multiplier = 1.5
        
        # Hard caps (never exceed these under any circumstances)
        self.absolute_max_notional_usd = config.get('risk', {}).get('absolute_max_notional_usd', 5000)
        self.absolute_max_position_pct = config.get('risk', {}).get('absolute_max_position_pct', 50)
        
        logger.info(f"🛡️ Position Size Validator initialized")
        logger.info(f"   Max notional multiplier: {self.max_notional_multiplier}x")
        logger.info(f"   Absolute max notional: ${self.absolute_max_notional_usd}")
        logger.info(f"   Absolute max position %: {self.absolute_max_position_pct}%")
        
    def validate_and_recalculate(self, signal, balance, risk_manager):
        """
        Validates position size from signal, recalculates if needed.
        
        MULTI-LAYER VALIDATION:
        1. Check if webhook provides position_size
        2. Compare webhook size vs risk-calculated size  
        3. Apply hard caps
        4. Log any anomalies
        5. Return safe validated size
        
        Args:
            signal: Signal dict from TradingView (UNTRUSTED)
            balance: Current trading balance (TRUSTED)
            risk_manager: Risk manager instance (TRUSTED)
        
        Returns:
            tuple: (is_valid, corrected_size, errors)
                - is_valid: True if safe to proceed, False if should abort
                - corrected_size: Safe position size in contracts/coins
                - errors: List of error messages (empty if valid)
        """
        errors = []
        symbol = signal['symbol']
        price = float(signal['price'])
        
        # STEP 1: Calculate what size SHOULD be based on risk rules
        expected_size = risk_manager.calculate_position_size(balance, price)
        expected_notional = expected_size * price
        
        logger.info(f"💡 Expected position size for {symbol}:")
        logger.info(f"   Balance: ${balance:.2f}")
        logger.info(f"   Price: ${price:.2f}")
        logger.info(f"   Expected size: {expected_size:.4f} contracts")
        logger.info(f"   Expected notional: ${expected_notional:.2f}")
        
        # STEP 2: Check if signal has position_size field (from webhook)
        signal_size = float(signal.get('position_size', 0))
        
        if signal_size > 0:
            signal_notional = signal_size * price
            
            logger.info(f"⚠️  Webhook provided position_size:")
            logger.info(f"   Webhook size: {signal_size:.4f} contracts")
            logger.info(f"   Webhook notional: ${signal_notional:.2f}")
            
            # STEP 3: Compare signal size vs expected size
            if expected_notional > 0:
                ratio = signal_notional / expected_notional
                logger.info(f"   Ratio: {ratio:.2f}x vs expected")
            else:
                ratio = float('inf')
                logger.error(f"❌ Expected notional is 0, cannot validate!")
            
            # STEP 4: Check if webhook size is dangerously oversized
            if ratio > self.max_notional_multiplier:
                errors.append(
                    f"REJECTED: Webhook position_size {signal_size:.4f} would create "
                    f"${signal_notional:.2f} notional ({ratio:.1f}x over limit of "
                    f"${expected_notional:.2f})"
                )
                logger.error(f"🚨🚨🚨 POSITION SIZE ANOMALY DETECTED! 🚨🚨🚨")
                logger.error(f"   Symbol: {symbol}")
                logger.error(f"   Webhook size: {signal_size:.4f} (${signal_notional:.2f})")
                logger.error(f"   Expected size: {expected_size:.4f} (${expected_notional:.2f})")
                logger.error(f"   Ratio: {ratio:.2f}x (max allowed: {self.max_notional_multiplier}x)")
                logger.error(f"   🛡️ OVERRIDING with safe calculated size to prevent catastrophic loss")
                
                # Log to a separate critical alert file
                try:
                    with open('logs/critical_alerts.log', 'a') as f:
                        import json
                        from datetime import datetime
                        alert = {
                            'timestamp': datetime.utcnow().isoformat(),
                            'alert_type': 'POSITION_SIZE_ANOMALY',
                            'signal_id': signal.get('signal_id'),
                            'symbol': symbol,
                            'webhook_size': signal_size,
                            'webhook_notional': signal_notional,
                            'expected_size': expected_size,
                            'expected_notional': expected_notional,
                            'ratio': ratio,
                            'action': 'OVERRIDE_WITH_SAFE_SIZE'
                        }
                        f.write(json.dumps(alert) + '\n')
                except Exception as e:
                    logger.error(f"Failed to write critical alert: {e}")
        else:
            logger.info(f"✓ No position_size in webhook, will use risk-calculated size")
        
        # STEP 5: Apply absolute hard caps (never exceed these)
        final_size = expected_size
        final_notional = final_size * price
        
        # Hard cap #1: Absolute max notional
        if final_notional > self.absolute_max_notional_usd:
            logger.warning(f"⚠️ Position notional ${final_notional:.2f} exceeds absolute max ${self.absolute_max_notional_usd}")
            final_size = self.absolute_max_notional_usd / price
            final_notional = final_size * price
            logger.info(f"   Capped to: {final_size:.4f} contracts (${final_notional:.2f})")
        
        # Hard cap #2: Absolute max % of balance
        max_position_value = balance * (self.absolute_max_position_pct / 100)
        if final_notional > max_position_value:
            logger.warning(f"⚠️ Position notional ${final_notional:.2f} exceeds {self.absolute_max_position_pct}% of balance")
            final_size = max_position_value / price
            final_notional = final_size * price
            logger.info(f"   Capped to: {final_size:.4f} contracts (${final_notional:.2f})")
        
        # STEP 6: Sanity check - ensure final size is reasonable
        if final_size <= 0:
            errors.append(f"Final position size is invalid: {final_size}")
            logger.error(f"❌ Invalid final position size: {final_size}")
            return False, 0, errors
        
        if final_notional < 10:  # Minimum $10 position (dust threshold)
            errors.append(f"Position too small: ${final_notional:.2f} < $10 minimum")
            logger.error(f"❌ Position too small: ${final_notional:.2f}")
            return False, 0, errors
        
        # STEP 7: Success - return validated size
        logger.info(f"✅ Position size VALIDATED for {symbol}:")
        logger.info(f"   Final size: {final_size:.4f} contracts")
        logger.info(f"   Final notional: ${final_notional:.2f}")
        logger.info(f"   % of balance: {(final_notional/balance)*100:.2f}%")
        
        return True, final_size, []
    
    def validate_before_execution(self, symbol, size, price, balance):
        """
        Final validation check immediately before order execution.
        This is the LAST LINE OF DEFENSE.
        
        Args:
            symbol: Trading symbol
            size: Position size in contracts/coins
            price: Entry price
            balance: Current balance
        
        Returns:
            tuple: (is_safe, error_msg)
        """
        notional = size * price
        
        # Final checks
        checks = []
        
        # Check 1: Notional within limits
        if notional > self.absolute_max_notional_usd:
            checks.append(f"Notional ${notional:.2f} > max ${self.absolute_max_notional_usd}")
        
        # Check 2: Size not negative or zero
        if size <= 0:
            checks.append(f"Size {size} is invalid (must be > 0)")
        
        # Check 3: Price is reasonable
        if price <= 0:
            checks.append(f"Price ${price} is invalid (must be > 0)")
        
        # Check 4: Notional vs balance ratio
        if notional > balance:
            checks.append(f"Notional ${notional:.2f} exceeds balance ${balance:.2f}")
        
        if checks:
            error_msg = " | ".join(checks)
            logger.error(f"❌ FINAL VALIDATION FAILED: {error_msg}")
            return False, error_msg
        
        logger.info(f"✅ FINAL VALIDATION PASSED: {symbol} {size:.4f} @ ${price:.2f} = ${notional:.2f}")
        return True, None

"""
Deterministic Client Order ID Generator for Exchange-Level Idempotency

Generates predictable client_order_ids based on signal properties, ensuring that
retries of the same signal produce the SAME ID, allowing exchanges (Binance) to
reject duplicates even if our idempotency layer fails.

Format: {signal_id}:{venue}:{leg}:{attempt}
- signal_id: Unique identifier from TradingView signal (e.g., "TV-20260212-abc123")
- venue: "entry", "sl", or "tp"
- leg: "main" (single order), "leg1", "leg2" (multiple TPs)
- attempt: Retry counter (default: "1")

Example IDs:
- TV-20260212-abc123:entry:main:1
- TV-20260212-abc123:sl:main:1
- TV-20260212-abc123:tp:leg1:1
- TV-20260212-abc123:tp:leg2:1
- TV-20260212-abc123:entry:main:2  (retry)

Benefits:
1. Exchange-level duplicate prevention (Binance rejects duplicate client_order_id)
2. Deterministic: Same signal → same ID → exchange blocks duplicate
3. Traceable: Can link entry/SL/TP orders back to originating signal
4. Retry-safe: Retry logic can increment attempt counter
"""

import hashlib
import re
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ClientOrderIdGenerator:
    """
    Generates deterministic client order IDs for exchange-level idempotency.
    
    Ensures that retries of the same signal generate the same client_order_id,
    allowing exchanges to reject duplicates.
    """
    
    # Max length for Binance client_order_id: 36 characters
    MAX_LENGTH = 36
    
    @staticmethod
    def _sanitize_signal_id(signal_id: str) -> str:
        """
        Sanitize signal ID to ensure it's exchange-safe.
        
        Rules:
        - Only alphanumeric, dash, underscore
        - Max 20 characters
        - If signal_id is missing, generate from timestamp + strategy
        
        Args:
            signal_id: Original signal identifier
            
        Returns:
            Sanitized signal ID (max 20 chars)
        """
        if not signal_id:
            # Fallback: Use hash of current timestamp
            import time
            signal_id = f"SIG{int(time.time())}"
        
        # Remove invalid characters
        sanitized = re.sub(r'[^a-zA-Z0-9\-_]', '', signal_id)
        
        # Truncate to 20 chars, or hash if too long
        if len(sanitized) > 20:
            # Hash to short form
            hash_digest = hashlib.sha256(sanitized.encode()).hexdigest()[:12]
            sanitized = f"SIG{hash_digest}"
        
        return sanitized
    
    @staticmethod
    def generate(
        signal_id: str,
        venue: str,
        leg: str = "main",
        attempt: int = 1,
        strategy: Optional[str] = None
    ) -> str:
        """
        Generate deterministic client order ID.
        
        Args:
            signal_id: Unique signal identifier (e.g., "TV-20260212-abc123")
            venue: Order type - "entry", "sl", "tp"
            leg: Order leg - "main", "leg1", "leg2", etc.
            attempt: Retry attempt number (default: 1)
            strategy: Optional strategy name for fallback ID generation
            
        Returns:
            Deterministic client_order_id (max 36 chars)
            
        Raises:
            ValueError: If venue is invalid or generated ID exceeds max length
            
        Example:
            >>> ClientOrderIdGenerator.generate("TV-123", "entry", "main", 1)
            'TV-123:entry:main:1'
            
            >>> ClientOrderIdGenerator.generate("TV-123", "tp", "leg2", 1)
            'TV-123:tp:leg2:1'
        """
        # Validate venue
        valid_venues = {"entry", "sl", "tp"}
        if venue not in valid_venues:
            raise ValueError(f"Invalid venue '{venue}'. Must be one of: {valid_venues}")
        
        # Validate attempt
        if attempt < 1 or attempt > 99:
            raise ValueError(f"Invalid attempt '{attempt}'. Must be between 1 and 99")
        
        # Sanitize signal ID
        clean_signal_id = ClientOrderIdGenerator._sanitize_signal_id(signal_id)
        
        # Build client_order_id
        client_order_id = f"{clean_signal_id}:{venue}:{leg}:{attempt}"
        
        # Validate length (Binance max: 36 chars)
        if len(client_order_id) > ClientOrderIdGenerator.MAX_LENGTH:
            # Truncate signal_id to fit
            max_signal_len = ClientOrderIdGenerator.MAX_LENGTH - len(f":{venue}:{leg}:{attempt}")
            clean_signal_id = clean_signal_id[:max_signal_len]
            client_order_id = f"{clean_signal_id}:{venue}:{leg}:{attempt}"
            
            logger.warning(f"⚠️ Truncated signal_id to fit max length: {client_order_id}")
        
        return client_order_id
    
    @staticmethod
    def parse(client_order_id: str) -> dict:
        """
        Parse client_order_id back into components.
        
        Args:
            client_order_id: Client order ID to parse
            
        Returns:
            Dictionary with keys: signal_id, venue, leg, attempt
            
        Example:
            >>> ClientOrderIdGenerator.parse("TV-123:entry:main:1")
            {'signal_id': 'TV-123', 'venue': 'entry', 'leg': 'main', 'attempt': 1}
        """
        parts = client_order_id.split(':')
        
        if len(parts) != 4:
            logger.warning(f"⚠️ Invalid client_order_id format: {client_order_id}")
            return {
                'signal_id': client_order_id,
                'venue': 'unknown',
                'leg': 'unknown',
                'attempt': 1
            }
        
        try:
            return {
                'signal_id': parts[0],
                'venue': parts[1],
                'leg': parts[2],
                'attempt': int(parts[3])
            }
        except (IndexError, ValueError) as e:
            logger.warning(f"⚠️ Failed to parse client_order_id: {client_order_id}, error: {e}")
            return {
                'signal_id': client_order_id,
                'venue': 'unknown',
                'leg': 'unknown',
                'attempt': 1
            }
    
    @staticmethod
    def generate_for_bracket(
        signal_id: str,
        attempt: int = 1
    ) -> dict:
        """
        Generate all client_order_ids for a bracket order (entry + SL + TP).
        
        Args:
            signal_id: Unique signal identifier
            attempt: Retry attempt number
            
        Returns:
            Dictionary with keys: entry, sl, tp
            
        Example:
            >>> ClientOrderIdGenerator.generate_for_bracket("TV-123")
            {
                'entry': 'TV-123:entry:main:1',
                'sl': 'TV-123:sl:main:1',
                'tp': 'TV-123:tp:main:1'
            }
        """
        return {
            'entry': ClientOrderIdGenerator.generate(signal_id, 'entry', 'main', attempt),
            'sl': ClientOrderIdGenerator.generate(signal_id, 'sl', 'main', attempt),
            'tp': ClientOrderIdGenerator.generate(signal_id, 'tp', 'main', attempt)
        }
    
    @staticmethod
    def generate_for_multiple_tps(
        signal_id: str,
        num_tps: int,
        attempt: int = 1
    ) -> dict:
        """
        Generate client_order_ids for entry + SL + multiple TPs.
        
        Args:
            signal_id: Unique signal identifier
            num_tps: Number of take-profit orders
            attempt: Retry attempt number
            
        Returns:
            Dictionary with keys: entry, sl, tp_1, tp_2, etc.
            
        Example:
            >>> ClientOrderIdGenerator.generate_for_multiple_tps("TV-123", 2)
            {
                'entry': 'TV-123:entry:main:1',
                'sl': 'TV-123:sl:main:1',
                'tp_1': 'TV-123:tp:leg1:1',
                'tp_2': 'TV-123:tp:leg2:1'
            }
        """
        result = {
            'entry': ClientOrderIdGenerator.generate(signal_id, 'entry', 'main', attempt),
            'sl': ClientOrderIdGenerator.generate(signal_id, 'sl', 'main', attempt)
        }
        
        for i in range(1, num_tps + 1):
            leg = f"leg{i}"
            result[f'tp_{i}'] = ClientOrderIdGenerator.generate(signal_id, 'tp', leg, attempt)
        
        return result


# ============================================================================
# TESTS
# ============================================================================

if __name__ == "__main__":
    import sys
    
    print("=" * 80)
    print("🧪 CLIENT ORDER ID GENERATOR - UNIT TESTS")
    print("=" * 80)
    print()
    
    passed = 0
    failed = 0
    
    # Test 1: Basic generation
    print("TEST 1: Basic client_order_id generation")
    print("-" * 80)
    try:
        id1 = ClientOrderIdGenerator.generate("TV-20260212-abc123", "entry", "main", 1)
        expected1 = "TV-20260212-abc123:entry:main:1"
        assert id1 == expected1, f"Expected {expected1}, got {id1}"
        assert len(id1) <= 36, f"ID too long: {len(id1)} chars"
        print(f"✅ Entry order ID: {id1}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 2: Deterministic (same input → same output)
    print("TEST 2: Deterministic generation")
    print("-" * 80)
    try:
        id_a = ClientOrderIdGenerator.generate("TV-123", "sl", "main", 1)
        id_b = ClientOrderIdGenerator.generate("TV-123", "sl", "main", 1)
        assert id_a == id_b, f"Not deterministic: {id_a} != {id_b}"
        print(f"✅ Same input produces same ID: {id_a}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 3: Different attempts generate different IDs
    print("TEST 3: Retry attempt differentiation")
    print("-" * 80)
    try:
        id_attempt1 = ClientOrderIdGenerator.generate("TV-123", "entry", "main", 1)
        id_attempt2 = ClientOrderIdGenerator.generate("TV-123", "entry", "main", 2)
        assert id_attempt1 != id_attempt2, "Attempts should generate different IDs"
        print(f"✅ Attempt 1: {id_attempt1}")
        print(f"✅ Attempt 2: {id_attempt2}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 4: Bracket order generation
    print("TEST 4: Bracket order ID generation")
    print("-" * 80)
    try:
        bracket = ClientOrderIdGenerator.generate_for_bracket("TV-XYZ")
        assert 'entry' in bracket and 'sl' in bracket and 'tp' in bracket
        assert bracket['entry'].startswith("TV-XYZ:entry")
        assert bracket['sl'].startswith("TV-XYZ:sl")
        assert bracket['tp'].startswith("TV-XYZ:tp")
        print(f"✅ Entry: {bracket['entry']}")
        print(f"✅ SL:    {bracket['sl']}")
        print(f"✅ TP:    {bracket['tp']}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 5: Multiple TPs
    print("TEST 5: Multiple take-profit orders")
    print("-" * 80)
    try:
        multi_tp = ClientOrderIdGenerator.generate_for_multiple_tps("TV-ABC", 3)
        assert 'entry' in multi_tp and 'sl' in multi_tp
        assert 'tp_1' in multi_tp and 'tp_2' in multi_tp and 'tp_3' in multi_tp
        print(f"✅ Entry: {multi_tp['entry']}")
        print(f"✅ SL:    {multi_tp['sl']}")
        print(f"✅ TP 1:  {multi_tp['tp_1']}")
        print(f"✅ TP 2:  {multi_tp['tp_2']}")
        print(f"✅ TP 3:  {multi_tp['tp_3']}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 6: Parsing
    print("TEST 6: Parse client_order_id")
    print("-" * 80)
    try:
        parsed = ClientOrderIdGenerator.parse("TV-123:entry:main:2")
        assert parsed['signal_id'] == "TV-123"
        assert parsed['venue'] == "entry"
        assert parsed['leg'] == "main"
        assert parsed['attempt'] == 2
        print(f"✅ Parsed: {parsed}")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Test 7: Long signal ID truncation
    print("TEST 7: Handle very long signal IDs")
    print("-" * 80)
    try:
        long_id = "TV-" + "x" * 50  # Very long signal ID
        truncated = ClientOrderIdGenerator.generate(long_id, "entry", "main", 1)
        assert len(truncated) <= 36, f"Truncated ID too long: {len(truncated)} chars"
        print(f"✅ Original length: {len(long_id)}")
        print(f"✅ Truncated: {truncated} ({len(truncated)} chars)")
        passed += 1
    except Exception as e:
        print(f"❌ FAILED: {e}")
        failed += 1
    print()
    
    # Summary
    print("=" * 80)
    print(f"📊 TEST SUMMARY")
    print("=" * 80)
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print(f"🎯 Score: {passed}/{passed + failed}")
    print()
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED!")
        sys.exit(1)

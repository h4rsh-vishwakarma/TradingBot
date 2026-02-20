import unittest
from storage.idempotency_store import init_db, is_seen, mark_as_seen
import os

class TestIdempotency(unittest.TestCase):
    def setUp(self):
        init_db()
        self.test_id = "test-unique-123"

    def test_single_execution(self):
        # First check: should not be seen
        self.assertFalse(is_seen(self.test_id))
        
        # Mark it as seen
        mark_as_seen(self.test_id)
        
        # Second check: MUST be seen
        self.assertTrue(is_seen(self.test_id))

if __name__ == "__main__":
    unittest.main()
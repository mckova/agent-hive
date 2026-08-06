from __future__ import annotations

import unittest

from src.rate_limiter import create_rate_limiter


class PublicCases(unittest.TestCase):
    def test_starts_full_and_consumes_tokens(self):
        limiter = create_rate_limiter({"capacity": 3, "refill_per_second": 1})
        self.assertTrue(limiter.allow("user", 2, 0)); self.assertEqual(limiter.peek("user", 0), 1)
        self.assertFalse(limiter.allow("user", 2, 0))

    def test_refills_continuously_and_caps_at_capacity(self):
        limiter = create_rate_limiter({"capacity": 4, "refill_per_second": 2})
        limiter.allow("user", 4, 1000)
        self.assertEqual(limiter.peek("user", 1250), 0.5); self.assertEqual(limiter.peek("user", 10000), 4)

    def test_keeps_keys_isolated_and_supports_reset(self):
        limiter = create_rate_limiter({"capacity": 2, "refill_per_second": 1})
        limiter.allow("a", 2, 0); self.assertEqual(limiter.peek("b", 0), 2)
        limiter.reset("a"); self.assertEqual(limiter.peek("a", 0), 2)
        limiter.reset(); self.assertEqual(limiter.size, 0)


if __name__ == "__main__":
    unittest.main()

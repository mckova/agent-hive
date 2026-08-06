import test from "node:test";
import assert from "node:assert/strict";
import { createRateLimiter } from "../src/rate-limiter.mjs";

test("starts full and consumes tokens", () => {
  const limiter = createRateLimiter({ capacity: 3, refillPerSecond: 1 });
  assert.equal(limiter.allow("user", 2, 0), true);
  assert.equal(limiter.peek("user", 0), 1);
  assert.equal(limiter.allow("user", 2, 0), false);
});

test("refills continuously and caps at capacity", () => {
  const limiter = createRateLimiter({ capacity: 4, refillPerSecond: 2 });
  limiter.allow("user", 4, 1000);
  assert.equal(limiter.peek("user", 1250), 0.5);
  assert.equal(limiter.peek("user", 10000), 4);
});

test("keeps keys isolated and supports reset", () => {
  const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1 });
  limiter.allow("a", 2, 0);
  assert.equal(limiter.peek("b", 0), 2);
  limiter.reset("a");
  assert.equal(limiter.peek("a", 0), 2);
  limiter.reset();
  assert.equal(limiter.size, 0);
});

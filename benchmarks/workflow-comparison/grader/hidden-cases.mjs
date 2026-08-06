import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import path from "node:path";

export async function runHiddenCases(targetDirectory) {
  const moduleUrl = `${pathToFileURL(path.join(targetDirectory, "src", "rate-limiter.mjs")).href}?grade=${Date.now()}`;
  const { createRateLimiter } = await import(moduleUrl);
  const cases = [
    ["exports factory", () => assert.equal(typeof createRateLimiter, "function"), "functional"],
    ["rejects invalid options", () => {
      for (const options of [
        { capacity: 0, refillPerSecond: 1 },
        { capacity: 1, refillPerSecond: Infinity },
        { capacity: 1, refillPerSecond: 1, maxKeys: 1.5 }
      ]) assert.throws(() => createRateLimiter(options), TypeError);
    }, "security"],
    ["rejects invalid calls", () => {
      const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1 });
      for (const call of [
        () => limiter.allow("", 1, 0),
        () => limiter.allow("x", 0, 0),
        () => limiter.allow("x", 1, NaN),
        () => limiter.peek("", 0)
      ]) assert.throws(call, TypeError);
    }, "security"],
    ["supports fractional refill", () => {
      const limiter = createRateLimiter({ capacity: 3, refillPerSecond: 0.5 });
      limiter.allow("x", 3, 100);
      assert.equal(limiter.peek("x", 600), 0.25);
    }, "functional"],
    ["caps refill", () => {
      const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 100 });
      limiter.allow("x", 2, 0);
      assert.equal(limiter.peek("x", 5000), 2);
    }, "functional"],
    ["denial advances monotonic refill time", () => {
      const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1 });
      limiter.allow("x", 2, 0);
      assert.equal(limiter.allow("x", 2, 1000), false);
      assert.equal(limiter.peek("x", 1500), 1.5);
    }, "functional"],
    ["backwards time neither refills nor rewinds", () => {
      const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1 });
      limiter.allow("x", 2, 1000);
      assert.equal(limiter.peek("x", 500), 0);
      assert.equal(limiter.peek("x", 1500), 0.5);
    }, "security"],
    ["uses LRU eviction", () => {
      const limiter = createRateLimiter({ capacity: 2, refillPerSecond: 1, maxKeys: 2 });
      limiter.allow("a", 2, 0);
      limiter.allow("b", 2, 0);
      limiter.peek("a", 0);
      limiter.allow("c", 2, 0);
      assert.equal(limiter.size, 2);
      assert.equal(limiter.allow("b", 2, 0), true);
    }, "security"],
    ["handles prototype-like keys safely", () => {
      const limiter = createRateLimiter({ capacity: 1, refillPerSecond: 1 });
      assert.equal(limiter.allow("__proto__", 1, 0), true);
      assert.equal(limiter.allow("constructor", 1, 0), true);
      assert.equal(limiter.size, 2);
    }, "security"],
    ["does not consume on peek", () => {
      const limiter = createRateLimiter({ capacity: 5, refillPerSecond: 1 });
      assert.equal(limiter.peek("x", 0), 5);
      assert.equal(limiter.peek("x", 0), 5);
      assert.equal(limiter.allow("x", 5, 0), true);
    }, "functional"],
    ["resets one or all buckets", () => {
      const limiter = createRateLimiter({ capacity: 1, refillPerSecond: 1 });
      limiter.allow("a", 1, 0);
      limiter.allow("b", 1, 0);
      limiter.reset("a");
      assert.equal(limiter.size, 1);
      assert.equal(limiter.allow("a", 1, 0), true);
      limiter.reset();
      assert.equal(limiter.size, 0);
    }, "functional"],
    ["does not create background handles", () => {
      const before = process._getActiveHandles().length;
      const limiter = createRateLimiter({ capacity: 1, refillPerSecond: 1 });
      for (let index = 0; index < 100; index += 1) limiter.allow(`key-${index}`, 1, index);
      assert.ok(process._getActiveHandles().length <= before + 1);
    }, "security"]
  ];

  const results = [];
  for (const [name, execute, category] of cases) {
    try {
      await execute();
      results.push({ name, category, passed: true });
    } catch (error) {
      results.push({ name, category, passed: false, error: error.message });
    }
  }
  return results;
}

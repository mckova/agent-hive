const SCOPES = new Set(["user", "project", "session", "mission", "team", "agent"]);

export class ScopedMemory {
  constructor(options = {}) {
    this.clock = options.clock || (() => new Date());
    this.onEvent = options.onEvent || (() => {});
    this.records = new Map();
    this.sequence = 0;
    for (const input of options.records || []) this.restore(input);
  }

  write(input) {
    assertScope(input.scope);
    if (typeof input.namespace !== "string" || !input.namespace.trim()) {
      throw new Error("memory.namespace must be a non-empty string.");
    }
    if (typeof input.content !== "string" || !input.content.trim()) {
      throw new Error("memory.content must be a non-empty string.");
    }
    const now = date(input.now || this.clock());
    const id = input.id || `mem-${++this.sequence}`;
    if (this.records.has(id)) throw new Error(`Duplicate memory id: ${id}`);
    const record = {
      id,
      scope: input.scope,
      namespace: input.namespace.trim(),
      kind: input.kind || "context",
      content: input.content,
      trust: input.trust === "trusted" ? "trusted" : "untrusted",
      confidence: unit(input.confidence, 1),
      relevance: unit(input.relevance, 1),
      sourceQuality: unit(input.sourceQuality, input.trust === "trusted" ? 1 : 0.5),
      verifiedUtility: unit(input.verifiedUtility, input.trust === "trusted" ? 1 : 0.5),
      sensitivity: unit(input.sensitivity, 0),
      reuseCount: nonNegativeInteger(input.reuseCount, 0),
      halfLifeMs: positive(input.halfLifeMs, 60 * 60 * 1000),
      ttlMs: input.ttlMs === null ? null : positive(input.ttlMs, 24 * 60 * 60 * 1000),
      status: input.status || "active",
      visibility: cleanVisibility(input.visibility, input.scope, input.namespace.trim()),
      createdAt: now.toISOString(),
      lastUsedAt: now.toISOString(),
      metadata: input.metadata && typeof input.metadata === "object" ? { ...input.metadata } : {}
    };
    this.records.set(id, record);
    this.emit("memory.write", record);
    return clone(record);
  }

  query(input) {
    assertScope(input.scope);
    if (typeof input.namespace !== "string" || !input.namespace.trim()) {
      throw new Error("query.namespace must be a non-empty string.");
    }
    const now = date(input.now || this.clock());
    const minimumScore = Number.isFinite(input.minimumScore) ? input.minimumScore : 0;
    const limit = positiveInteger(input.limit, 10);
    const rows = [...this.records.values()]
      .filter((record) => record.scope === input.scope && record.namespace === input.namespace)
      .filter((record) => ["active", "cooling"].includes(record.status))
      .filter((record) => canRead(record, input.role))
      .filter((record) => input.trustedOnly !== true || record.trust === "trusted")
      .filter((record) => record.sensitivity <= unit(input.maxSensitivity, 0.5))
      .map((record) => ({ ...record, retentionScore: retentionScore(record, now) }))
      .filter((record) => record.retentionScore >= minimumScore)
      .sort((left, right) => right.retentionScore - left.retentionScore || left.id.localeCompare(right.id))
      .slice(0, limit);
    for (const row of rows) {
      const stored = this.records.get(row.id);
      stored.lastUsedAt = now.toISOString();
      this.emit("memory.read", stored, { role: input.role || "*", retentionScore: row.retentionScore });
    }
    return rows.map(clone);
  }

  reinforce(id, options = {}) {
    const record = this.records.get(id);
    if (!record) throw new Error(`Unknown memory id: ${id}`);
    if (!options.verified || !options.successful) {
      this.emit("memory.reinforce_skipped", record);
      return clone(record);
    }
    record.reuseCount += 1;
    record.verifiedUtility = Math.min(1, record.verifiedUtility + 0.05);
    record.lastUsedAt = date(options.now || this.clock()).toISOString();
    record.status = "active";
    this.emit("memory.reinforced", record);
    return clone(record);
  }

  decay(options = {}) {
    const now = date(options.now || this.clock());
    const coolingThreshold = finite(options.coolingThreshold, 0.4);
    const archiveThreshold = finite(options.archiveThreshold, 0.2);
    const deleteThreshold = finite(options.deleteThreshold, 0.05);
    const summary = { cooled: 0, archived: 0, deleted: 0 };
    for (const record of [...this.records.values()]) {
      const age = now.getTime() - new Date(record.createdAt).getTime();
      const expired = record.ttlMs !== null && age >= record.ttlMs;
      const score = retentionScore(record, now);
      if (expired || score < deleteThreshold) {
        this.records.delete(record.id);
        summary.deleted += 1;
        this.emit("memory.deleted", record, { expired, retentionScore: score });
      } else if (score < archiveThreshold) {
        record.status = "archived";
        summary.archived += 1;
        this.emit("memory.archived", record, { retentionScore: score });
      } else if (score < coolingThreshold && record.status === "active") {
        record.status = "cooling";
        summary.cooled += 1;
        this.emit("memory.cooled", record, { retentionScore: score });
      }
    }
    return summary;
  }

  deleteScope({ scope, namespace, reason = "scope_expired" }) {
    assertScope(scope);
    let deleted = 0;
    for (const record of [...this.records.values()]) {
      if (record.scope !== scope || record.namespace !== namespace) continue;
      this.records.delete(record.id);
      deleted += 1;
      this.emit("memory.deleted", record, { reason });
    }
    return deleted;
  }

  snapshot(options = {}) {
    return [...this.records.values()].map((record) => {
      const output = clone(record);
      if (!options.includeContent) delete output.content;
      return output;
    });
  }

  export() {
    return {
      schemaVersion: 1,
      records: this.snapshot({ includeContent: true })
    };
  }

  restore(input) {
    if (!input || typeof input !== "object" || typeof input.id !== "string") {
      throw new Error("Invalid memory record.");
    }
    assertScope(input.scope);
    const record = clone(input);
    record.trust = input.trust === "trusted" ? "trusted" : "untrusted";
    record.visibility = cleanVisibility(input.visibility, input.scope, input.namespace);
    date(record.createdAt);
    date(record.lastUsedAt);
    this.records.set(record.id, record);
    const numeric = Number(record.id.match(/^mem-(\d+)$/)?.[1]);
    if (Number.isInteger(numeric)) this.sequence = Math.max(this.sequence, numeric);
  }

  emit(type, record, extra = {}) {
    this.onEvent({
      type,
      memoryId: record.id,
      scope: record.scope,
      namespace: record.namespace,
      kind: record.kind,
      at: this.clock().toISOString(),
      ...extra
    });
  }
}

export function retentionScore(record, now = new Date()) {
  const age = Math.max(0, date(now).getTime() - new Date(record.lastUsedAt || record.createdAt).getTime());
  const timeStrength = 2 ** (-age / positive(record.halfLifeMs, 1));
  const reuseBoost = Math.min(0.2, Math.log2(1 + nonNegativeInteger(record.reuseCount, 0)) * 0.04);
  const base = timeStrength
    * unit(record.confidence, 1)
    * unit(record.relevance, 1)
    * unit(record.sourceQuality, 1)
    * unit(record.verifiedUtility, 1);
  return Math.max(0, Math.min(1, base + reuseBoost - unit(record.sensitivity, 0) * 0.25));
}

function canRead(record, role) {
  return record.visibility.includes("*") || (role && record.visibility.includes(role));
}

function assertScope(scope) {
  if (!SCOPES.has(scope)) throw new Error(`memory.scope must be one of ${[...SCOPES].join(", ")}.`);
}

function cleanVisibility(value, scope, namespace) {
  if (value === undefined) return scope === "agent" ? [namespace] : ["*"];
  if (!Array.isArray(value) || !value.length || value.some((item) => typeof item !== "string" || !item.trim())) {
    throw new Error("memory.visibility must be a non-empty array of strings.");
  }
  return [...new Set(value.map((item) => item.trim()))];
}

function unit(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}

function positive(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function finite(value, fallback) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

function positiveInteger(value, fallback) {
  return Number.isInteger(value) && value > 0 ? value : fallback;
}

function nonNegativeInteger(value, fallback) {
  return Number.isInteger(value) && value >= 0 ? value : fallback;
}

function date(value) {
  const result = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(result.getTime())) throw new Error("Invalid memory timestamp.");
  return result;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

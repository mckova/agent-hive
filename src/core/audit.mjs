import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";

const SECRET_KEY = /authorization|api[-_]?key|secret|password|access[-_]?token|refresh[-_]?token|cookie/i;
const CONTENT_KEY = /^(prompt|input|content|memory|reusableContext|messages)$/i;

export async function appendAudit(filePath, event, clock = () => new Date()) {
  const safe = redact({ schemaVersion: 1, at: clock().toISOString(), ...event });
  await mkdir(path.dirname(filePath), { recursive: true });
  await appendFile(filePath, `${JSON.stringify(safe)}\n`, "utf8");
  return safe;
}

export function redact(value, key = "") {
  if (SECRET_KEY.test(key) || key.toLowerCase() === "token" || CONTENT_KEY.test(key)) return "[REDACTED]";
  if (Array.isArray(value)) return value.map((item) => redact(item));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value).map(([childKey, child]) => [childKey, redact(child, childKey)]));
}
